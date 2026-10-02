import asyncio
import json
from ollama import chat
from playwright.async_api import async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

# Fill in the challenge details
URL = ""
USERNAME = ""
PASSWORD = ""
QUESTION = ""

MODEL = "qwen3:4b"

async def login(page, username, password):

    print("\nLooking for login fields...")

    # -----------------------------------------
    # Find username field
    # -----------------------------------------

    username_input = page.locator(
        'input[type="text"], '
        'input[type="email"], '
        'input[name*="user" i], '
        'input[id*="user" i]'
    ).first

    # -----------------------------------------
    # Find password field
    # -----------------------------------------

    password_input = page.locator(
        'input[type="password"]'
    ).first

    if await username_input.count() == 0:
        raise Exception("Username field not found.")

    if await password_input.count() == 0:
        raise Exception("Password field not found.")

    print("Login fields found.")

    # -----------------------------------------
    # Fill credentials
    # -----------------------------------------

    await username_input.fill(username)
    await password_input.fill(password)

    print("Username and password filled.")

    # -----------------------------------------
    # First try Enter from the password field
    # -----------------------------------------

    print("Trying Enter from password field...")

    await password_input.press("Enter")

    await page.wait_for_timeout(1000)

    # Check whether the login fields disappeared
    if not await password_input.is_visible():
        print("Login fields disappeared.")
        print("Login succeeded using Enter.")
        print("After login:", page.url)

        return

    print("Login fields are still visible.")
    print("Looking for login button...")

    # -----------------------------------------
    # Find the closest common ancestor
    # containing username + password
    # -----------------------------------------

    common_parent = password_input.locator(
        "xpath=ancestor::*[.//input["
        "@type='text' or "
        "@type='email' or "
        "contains(translate(@name, 'USER', 'user'), 'user') or "
        "contains(translate(@id, 'USER', 'user'), 'user')"
        "]][1]"
    )

    if await common_parent.count() == 0:
        raise Exception("Could not find login area.")

    # -----------------------------------------
    # Start close to the login fields
    # and gradually move outward
    # -----------------------------------------

    current = common_parent

    login_button = None

    for level in range(6):

        print(f"Searching for button at DOM level {level}...")

        buttons = current.locator(
            'button, input[type="submit"]'
        )

        for i in range(await buttons.count()):

            button = buttons.nth(i)

            if await button.is_visible():
                login_button = button
                break

        if login_button is not None:
            break

        # Move one level up
        current = current.locator("xpath=..")

    # -----------------------------------------
    # Nothing found nearby
    # -----------------------------------------

    if login_button is None:
        raise Exception(
            "No login button found near username/password."
        )

    # -----------------------------------------
    # Click
    # -----------------------------------------

    print("Login button found near login fields.")
    print("Logging in...")

    await login_button.click()

    await page.wait_for_load_state(
        "domcontentloaded"
    )

    await page.wait_for_timeout(1000)

    print("After login:", page.url)
# =========================================================
# READ PAGE
# =========================================================

async def read_page(page):

    # -----------------------------------------
    # 1. Visible text
    # -----------------------------------------

    visible_text = await page.locator("body").inner_text()

    # -----------------------------------------
    # 2. Hidden DOM elements only
    # -----------------------------------------

    hidden_data = await page.locator("body *").evaluate_all("""
        elements => elements.map(el => {

            const style = getComputedStyle(el);

            const isHidden =
                el.hidden ||
                style.display === "none" ||
                style.visibility === "hidden" ||
                style.opacity === "0";

            if (!isHidden) {
                return null;
            }

            const attributes = {};

            for (const attr of el.attributes) {
                attributes[attr.name] = attr.value;
            }

            return {
                tag: el.tagName.toLowerCase(),
                text: (el.textContent || "").trim(),
                attributes: attributes
            };

        }).filter(item =>
            item !== null &&
            (
                item.text ||
                Object.keys(item.attributes).length > 0
            )
        )
    """)

    return visible_text, hidden_data

async def find_search_box(page):

    selectors = [
        'input[type="search"]',
        'input[name*="search" i]',
        'input[id*="search" i]',
        'input[placeholder*="search" i]',
        'textarea[name*="search" i]',
        'textarea[placeholder*="search" i]'
    ]

    for selector in selectors:

        locator = page.locator(selector)

        if await locator.count() > 0:

            for i in range(await locator.count()):

                element = locator.nth(i)

                if await element.is_visible():
                    return element

    return None

async def search_page(page, question):

    search_box = await find_search_box(page)

    if search_box is None:
        print("\nNo search box found.")
        return None

    print("\nSearch box found.")
    print("Searching for:", question)

    # Save current visible text so we can detect a change
    before_search = await page.locator("body").inner_text()

    await search_box.fill(question)
    await search_box.press("Enter")

    # Give the page time to update
    await page.wait_for_timeout(2000)

    after_search = await page.locator("body").inner_text()

    if after_search == before_search:
        print("Search did not change the page.")
        return None

    print(
        "Search result text characters:",
        len(after_search)
    )

    return after_search

def ask_llm(question, page_content):

    prompt = f"""
Answer the QUESTION using only the WEBPAGE CONTENT below.

QUESTION:
{question}

WEBPAGE CONTENT:
{page_content}

Find information in the webpage that answers the question.

The wording in the webpage may be different from the wording
of the question. Understand the meaning of the text.

Use ONLY the webpage content.
Do NOT use outside knowledge.
Do NOT guess.

If the answer exists in the webpage, return the answer.
If the webpage does not contain the answer, return "NOT FOUND".
"""

    response = chat(
        model=MODEL,

        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ],

        think=False,

        format={
            "type": "object",
            "properties": {
                "answer": {
                    "type": "string"
                }
            },
            "required": ["answer"]
        },

        options={
            "temperature": 0,
            "num_predict": 200
        }
    )

    result = json.loads(
        response["message"]["content"]
    )

    print("\nLLM DEBUG:")
    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False
        )
    )

    return result["answer"]

async def try_action_buttons(page, question):

    buttons = page.locator('button[type="button"]')

    for i in range(await buttons.count()):

        button = buttons.nth(i)

        if not await button.is_visible():
            continue

        text = (await button.inner_text()).strip()

        if not text:
            continue

        print("Found action button:", text)

        lower_text = text.lower()

        action_words = [
            "load",
            "show",
            "reveal",
            "view"
        ]

        if not any(word in lower_text for word in action_words):
            continue

        print("Trying action button:", text)

        await button.click(timeout=3000)

        # Wait until an output element actually contains data
        try:
            await page.wait_for_function(
                """
                () => {
                    const outputs = document.querySelectorAll('output');
                    return Array.from(outputs).some(
                        el => el.textContent.trim().length > 0
                    );
                }
                """,
                timeout=10000
            )
        except PlaywrightTimeoutError:
            print("No output appeared after action.")
            continue

        # Read output directly from the browser DOM
        outputs = page.locator("output")

        for j in range(await outputs.count()):

            output_text = (
                await outputs.nth(j).text_content()
            )

            if not output_text:
                continue

            output_text = output_text.strip()

            if not output_text:
                continue

            print("Output found:", output_text)

            return output_text

    return "NOT FOUND"

async def get_links(page):

    links = page.locator("a[href]")
    result = []

    for i in range(await links.count()):

        link = links.nth(i)

        text = (await link.inner_text()).strip()

        if not text:
            continue

        href = await link.get_attribute("href")

        if not href:
            continue

        visible = await link.is_visible()

        result.append({
            "text": text,
            "href": href,
            "visible": visible
        })

    return result

def is_link_relevant(question, link_text):
    prompt = f"""
    You are browsing a website to find the answer to a question.

    QUESTION:
    {question}

    LINK TITLE:
    {link_text}

    Decide whether opening this link could reasonably help find
    the answer to the question.

    Use ONLY the QUESTION and the LINK TITLE.
    Do NOT use outside knowledge.
    Do NOT answer the question.

    A link is worth opening if its title gives any reasonable
    indication that the page it leads to may contain the answer
    or information that could help find the answer.

    Consider both:
    - whether the subject or meaning of the title is related to
      the question;
    - whether the wording or intent of the title suggests that
      the destination page may contain the information being
      searched for, even if the subject of the question is not
      explicitly mentioned.

    The title does not need to prove that the answer is there.
    It only needs to provide a reasonable reason to explore the page.

    If there is a reasonable possibility that the page could help,
    return true.
    Otherwise return false.
    """

    response = chat(
        model=MODEL,

        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ],

        think=False,

        format={
            "type": "object",
            "properties": {
                "relevant": {
                    "type": "boolean"
                }
            },
            "required": ["relevant"]
        },

        options={
            "temperature": 0,
            "num_predict": 50
        }
    )

    result = json.loads(
        response["message"]["content"]
    )

    return result["relevant"]

async def explore_links(page, question, links, depth=0, max_depth=2):

    relevant_links = []
    other_links = []

    print(f"\nClassifying links at depth {depth}...")

    for index, link in enumerate(links):

        relevant = is_link_relevant(
            question,
            link["text"]
        )

        visibility = (
            "visible"
            if link["visible"]
            else "hidden"
        )

        print(
            f"[{index}] {link['text']} "
            f"({visibility}) -> Relevant: {relevant}"
        )

        if relevant:
            relevant_links.append((index, link))
        else:
            other_links.append((index, link))

    ordered_links = relevant_links + other_links

    print("\nExploration order:")

    for index, link in ordered_links:
        print(
            f"[{index}] {link['text']} "
            f"({'visible' if link['visible'] else 'hidden'})"
        )

    for index, link in ordered_links:

        print("\n----------------------")
        print(f"Opening [{index}] {link['text']}")
        print("----------------------")

        parent_url = page.url

        # -----------------------------------------
        # Visible link -> normal browser click
        # -----------------------------------------

        if link["visible"]:

            page_links = page.locator("a[href]")
            link_to_click = None

            for i in range(await page_links.count()):

                candidate = page_links.nth(i)

                href = await candidate.get_attribute("href")

                if (
                    href == link["href"]
                    and await candidate.is_visible()
                ):
                    link_to_click = candidate
                    break

            if link_to_click is None:
                print("Could not find visible link on page.")
                continue

            try:
                await link_to_click.click(
                    timeout=3000
                )

            except PlaywrightTimeoutError:
                print("Link could not be clicked.")
                print("Skipping this link.")
                continue

        # -----------------------------------------
        # Hidden link -> navigate using its href
        # -----------------------------------------

        else:

            print(
                "Link is hidden. "
                "Navigating through its href..."
            )

            href = link["href"]

            # Resolve relative URL using the browser
            target_url = await page.evaluate(
                "(href) => new URL(href, window.location.href).href",
                href
            )

            await page.goto(
                target_url,
                wait_until="domcontentloaded"
            )

        await page.wait_for_load_state(
            "domcontentloaded"
        )

        await page.wait_for_timeout(1000)

        print("Opened:", page.url)

        # -----------------------------------------
        # Check visible content
        # -----------------------------------------

        visible_text, hidden_data = await read_page(page)

        print("Checking visible text...")

        answer = ask_llm(
            question,
            visible_text
        )

        # -----------------------------------------
        # Check hidden content
        # -----------------------------------------

        if answer == "NOT FOUND":

            print("Answer not found in visible text.")
            print("Checking hidden content...")

            hidden_content = json.dumps(
                hidden_data,
                ensure_ascii=False
            )

            answer = ask_llm(
                question,
                hidden_content
            )

        # -----------------------------------------
        # Answer found
        # -----------------------------------------

        if answer != "NOT FOUND":

            print(
                "\nAnswer found after opening link:",
                link["text"]
            )

            return answer

        if answer == "NOT FOUND":
            print("Answer not found in page content.")
            print("Looking for action buttons...")

            answer = await try_action_buttons(
                page,
                question
            )

        if answer != "NOT FOUND":
            print(
                "\nAnswer found after interaction on:",
                page.url
            )

            return answer
        # -----------------------------------------
        # NEW: look for links one level deeper
        # -----------------------------------------

        if depth < max_depth:

            child_links = await get_links(page)

            if child_links:

                print(
                    f"\nAnswer not found, but found "
                    f"{len(child_links)} links on this page."
                )

                child_answer = await explore_links(
                    page,
                    question,
                    child_links,
                    depth=depth + 1,
                    max_depth=max_depth
                )

                if child_answer != "NOT FOUND":
                    return child_answer

        # -----------------------------------------
        # Return to parent page
        # -----------------------------------------

        print("Answer not found on this branch.")
        print("Returning to previous page...")

        if page.url != parent_url:

            await page.goto(
                parent_url,
                wait_until="domcontentloaded"
            )

            await page.wait_for_timeout(1000)

    return "NOT FOUND"

async def find_answer_input(page):

    selectors = [
        'input[name*="answer" i]',
        'input[id*="answer" i]',
        'input[placeholder*="answer" i]',
        'textarea[name*="answer" i]',
        'textarea[id*="answer" i]',
        'textarea[placeholder*="answer" i]'
    ]

    for selector in selectors:

        locator = page.locator(selector)

        for i in range(await locator.count()):

            element = locator.nth(i)

            if await element.is_visible():
                return element

    return None

async def prepare_answer(page, answer, original_url):

    print("\nLooking for answer input...")

    answer_input = await find_answer_input(page)

    # Maybe we found the answer on another page
    if answer_input is None and page.url != original_url:

        print("Answer input not found on current page.")
        print("Returning to main page...")

        await page.goto(
            original_url,
            wait_until="domcontentloaded"
        )

        await page.wait_for_timeout(1000)

        answer_input = await find_answer_input(page)

    if answer_input is None:
        raise Exception("Answer input not found.")

    print("Answer input found.")

    await answer_input.fill(answer)

    print("Answer entered:", answer)

    return answer_input

async def find_submission_input(page, original_url):

    print("\nLooking for answer input on current page...")

    answer_input = await find_answer_input(page)

    if answer_input is not None:
        print("Answer input found on current page.")
        return answer_input

    if page.url != original_url:
        print("Answer input not found on current page.")
        print("Returning to main page...")

        await page.goto(
            original_url,
            wait_until="domcontentloaded"
        )

        await page.wait_for_timeout(1000)

        answer_input = await find_answer_input(page)

        if answer_input is not None:
            print("Answer input found on main page.")
            return answer_input

    return None

async def find_nearby_button(input_element):

    current = input_element

    for level in range(6):

        print(f"Searching for button at DOM level {level}...")

        buttons = current.locator(
            'button, input[type="submit"], input[type="button"]'
        )

        visible_buttons = []

        for i in range(await buttons.count()):

            button = buttons.nth(i)

            if await button.is_visible():
                visible_buttons.append(button)

        if len(visible_buttons) == 1:
            print("Nearby button found.")
            return visible_buttons[0]

        if len(visible_buttons) > 1:
            print(
                f"Found {len(visible_buttons)} buttons "
                "at this DOM level. Not choosing automatically."
            )
            return None

        current = current.locator("..")

    return None

async def main():

    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=False
        )

        page = await browser.new_page()

        # -----------------------------------------
        # Open website
        # -----------------------------------------

        await page.goto(
            URL,
            wait_until="domcontentloaded"
        )

        await page.wait_for_timeout(3000)

        # -----------------------------------------
        # LOGIN
        # -----------------------------------------

        await login(
            page,
            USERNAME,
            PASSWORD
        )

        print("\nPage:", page.url)

        # Save the original page
        original_url = page.url

        # -----------------------------------------
        # Read visible text + hidden DOM
        # -----------------------------------------

        visible_text, hidden_data = await read_page(page)

        print(
            "Visible text characters:",
            len(visible_text)
        )

        print(
            "Hidden DOM elements:",
            len(hidden_data)
        )

        # -----------------------------------------
        # STEP 1 - Check visible text
        # -----------------------------------------

        print("\nChecking visible text...")

        answer = ask_llm(
            QUESTION,
            visible_text
        )

        # -----------------------------------------
        # STEP 2 - If not visible, check hidden DOM
        # -----------------------------------------

        if answer == "NOT FOUND":

            print("\nAnswer not found in visible text.")
            print("Checking hidden content...")

            hidden_content = json.dumps(
                hidden_data,
                ensure_ascii=False
            )

            answer = ask_llm(
                QUESTION,
                hidden_content
            )

        # -----------------------------------------
        # STEP 3 - If still not found, try search
        # -----------------------------------------

        if answer == "NOT FOUND":

            print("\nAnswer not found in hidden content.")
            print("Looking for a search box...")

            search_results = await search_page(
                page,
                QUESTION
            )

            if search_results is not None:

                print("\nChecking search results...")

                answer = ask_llm(
                    QUESTION,
                    search_results
                )

        # -----------------------------------------
        # STEP 4 - If still not found, explore links
        # -----------------------------------------

        if answer == "NOT FOUND":

            # Search may have changed the page.
            # Return to the original page first.
            if page.url != original_url:

                print("\nReturning to original page...")

                await page.goto(
                    original_url,
                    wait_until="domcontentloaded"
                )

                await page.wait_for_timeout(1000)

            # Collect links only now
            links = await get_links(page)

            print(
                "\nVisible links found:",
                len(links)
            )

            print("\nAnswer still not found.")
            print("Exploring links...")

            answer = await explore_links(
                page,
                QUESTION,
                links
            )

        # -----------------------------------------
        # Final result
        # -----------------------------------------

        print("\n======================")
        print("ANSWER:")
        print(answer)
        print("======================")

        if answer != "NOT FOUND":

            answer_input = await find_submission_input(
                page,
                original_url
            )

            if answer_input is None:
                raise Exception("Answer input not found.")

            await answer_input.fill(answer)

            print("\nAnswer entered:", answer)

            while True:

                confirmation = input(
                    "Submit this answer? [y/N]: "
                ).strip().lower()

                if confirmation == "y":
                    break

                answer = input(
                    "Enter the answer manually: "
                ).strip()

                await answer_input.fill(answer)

                print("\nAnswer updated:", answer)

            print("\nAnswer approved for submission.")
            print("Looking for submit button near answer input...")

            submit_button = await find_nearby_button(answer_input)

            if submit_button is None:
                raise Exception(
                    "No submit button found near answer input."
                )

            print("Submit button found.")
            print("Submitting answer...")

            await submit_button.click()

            print("\nSubmission clicked.")

            try:
                await page.wait_for_function(
                    """
                    () => {
                        const status = document.querySelector('[role="status"]');
                        return status && status.textContent.trim().length > 0;
                    }
                    """,
                    timeout=10000
                )

                status = await page.locator('[role="status"]').text_content()

                print("Submission result:", status.strip())

            except PlaywrightTimeoutError:
                print("No submission status appeared within 10 seconds.")

            input("\nPress Enter to close the browser...")

        await browser.close()


asyncio.run(main())