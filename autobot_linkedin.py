import os
import re
import json
import time
import datetime
import pandas as pd
import random
import gspread
import requests
import pickle
import traceback
import io
import tempfile

from googleapiclient.discovery import build
from oauth2client.service_account import ServiceAccountCredentials
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.keys import Keys
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException
from IPython.display import Image, display
from googleapiclient.http import MediaIoBaseDownload

"""# **BIẾN GLOBAL CHUNG**"""

# LẤY TỪ SECRETS ENV TRONG SETTINGS CỦA REPO
MISSIVE_API_KEY = os.environ.get("MISSIVE_API_KEY")
HEADERS = {
    "Authorization": f"Bearer {MISSIVE_API_KEY}",
    "Content-Type": "application/json",
}
PARAMS = {"limmit": 20, "inbox": "true"}
COOKIES_FILE = "cookie.pkl"
CREDENTIALS_FILE = "credential.pkl"
USERNAME = os.environ.get("USERNAME")
PASSWORD = os.environ.get("PASSWORD")

"""# **Kết nối đến Google Sheet và nhập dữ liệu từ Google Sheet**"""

scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
# Khởi tạo creds từ file JSON (thay vì bắt người dùng tự đăng nhập như trên Colab)
creds_json = os.environ.get("GOOGLE_CREDENTIALS")
if not creds_json:
    raise ValueError("GOOGLE_CREDENTIALS environment variable not set")
creds_dict = json.loads(creds_json)
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
# CREATE THE SERVICE.
service = build("sheets", "v4", credentials=creds)
# SPREEDSHEET GỐC.
spreadsheet_ID = "1zsz3xw7_A1nD_xemikEJY1pXHAeBSVthG_MWDSCMx5E"
# RANGE MỞ RỘNG (TỪ A ĐẾN I ĐỂ CHỨA LINK VÀ DATE)
range_name = "input_linkedin!A:I"
# CALL GOOGLE SHEETS API.
sheet = service.spreadsheets()
result = sheet.values().get(spreadsheetId=spreadsheet_ID, range=range_name).execute()
values = result.get("values", [])
# ENSURE ALL ROWS HAVE THE SAME NUMBER OF COLUMNS.
max_cols = max(len(row) for row in values)
values = [row + [""] * (max_cols - len(row)) for row in values]
# CONVERT TO DATAFRAME.
df = pd.DataFrame(values[1:], columns=values[0])
# FILL ALL NAN WITH AN EMPTY STRING.
df = df.fillna("")

# Đảm bảo 2 cột mới tồn tại trong DataFrame để tránh lỗi nếu Google Sheet gõ sai tên
if "Link bài đã post" not in df.columns:
    df["Link bài đã post"] = ""
if "Date post" not in df.columns:
    df["Date post"] = ""

df.head()

"""# **Thực hiện đăng nhập vào tài khoản Linkedin**"""


def save_display_screenshot(driver, screenshot_path):
    driver.save_screenshot(screenshot_path)
    display(Image(filename=screenshot_path))


def get_driver():
    options = Options()
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    options.add_argument(f"user-agent={user_agent}")
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-notifications")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_window_size(1920, 1200)

    driver.execute_script("""
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        })
        """)
    return driver


browser = get_driver()
browser.implicitly_wait(15)

browser.get("https://www.linkedin.com/login?fromSignIn=true")
time.sleep(5)
screenshot_path = "screenshot.png"
save_display_screenshot(browser, screenshot_path)


def human_type(element, text):
    driver = element.parent
    ActionChains(driver).send_keys(text).perform()
    time.sleep(random.uniform(1, 2))


def handle_cookie_acceptance(driver: webdriver.Chrome):
    try:
        driver.find_element(By.XPATH, "//button[span[text()='Accept']]").click()
        print("INFO: COOKIES IS ACCEPTED!")
    except:
        print("INFO: COOKIES IS NOT REQUIRED!")


def save_cookies(driver):
    with open(COOKIES_FILE, "wb") as cookies_file:
        pickle.dump(driver.get_cookies(), cookies_file)
    print("INFO: COOKIES SAVED!")


def load_cookies(driver: webdriver.Chrome, file_name: str):
    if os.path.exists(file_name):
        with open(file_name, "rb") as f:
            cookies = pickle.load(f)
            for cookie in cookies:
                driver.add_cookie(cookie)


def load_credentials(driver, file_path):
    with open(file_path, "rb") as file:
        return pickle.load(file)


def save_credentials(username, password, file_path):
    with open(file_path, "wb") as file:
        pickle.dump({"username": username, "password": password}, file)


def handle_code_verification(driver: webdriver.Chrome):
    try:
        ID_FIELD = "input__email_verification_pin"
        CONDITION = EC.presence_of_element_located((By.ID, ID_FIELD))
        verification_field = WebDriverWait(driver, 20).until(CONDITION)

        ID_FIELD = "email-pin-submit-button"
        CONDITION = EC.presence_of_element_located((By.ID, ID_FIELD))
        submit_button = WebDriverWait(driver, 20).until(CONDITION)

        code = get_missive_linkedin_code()
        print(code)
        driver.save_screenshot("before_verification.png")
        time.sleep(2)
        verification_field.send_keys(code)
        time.sleep(3)
        submit_button.click()
        time.sleep(5)
    except:
        print("INFO: NO VERIFICATION DETECTED!")


def get_missive_linkedin_code():
    response = requests.get(
        "https://public.missiveapp.com/v1/conversations", headers=HEADERS, params=PARAMS
    )
    if response.status_code != 200:
        return f"Lỗi API: {response.status_code}"
    conversations = response.json().get("conversations", [])
    temp = [
        c["latest_message_subject"]
        for c in conversations
        if "name" in c["authors"][0] and c["authors"][0]["name"] == "LinkedIn"
    ]
    final_temp = [f.split(" ")[-1:][0] for f in temp]
    for item in final_temp:
        if item.isdigit():
            return item
    return None


def login(driver, username: str, password: str):
    XPATH_USERNAME = '//input[@id="username" or @name="session_key" or @autocomplete="username" or @type="email" or @type="text"]'
    XPATH_PASSWORD = '//input[@id="password" or @name="session_password" or @autocomplete="current-password" or @type="password"]'
    XPATH_LOGIN_BUTTON = '//button[contains(@class, "btn__primary--large") or @type="submit" or @aria-label="Sign in"]'

    try:
        credentials = load_credentials(driver, CREDENTIALS_FILE)
        input_username = credentials["username"]
        input_password = credentials["password"]
    except:
        print(
            "INFO: Không có file credentials.pkl, dùng biến môi trường username và password"
        )
        input_username = username
        input_password = password
        save_credentials(input_username, input_password, CREDENTIALS_FILE)

    driver.get("https://www.linkedin.com/login")
    time.sleep(2)

    if os.path.exists(COOKIES_FILE):
        load_cookies(driver, COOKIES_FILE)
        driver.get("https://www.linkedin.com/feed")
        time.sleep(5)

        try:
            WebDriverWait(driver, 10).until(lambda d: "feed" in d.current_url)
            print("INFO: Logged in using cookies!")
            return
        except:
            print(
                "INFO: Cookies chưa vào thẳng Feed. Đang kiểm tra màn hình Welcome Back..."
            )
            try:
                pwd_field = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located(
                        (
                            By.XPATH,
                            "//input[@type='password' or @id='password' or @name='session_password']",
                        )
                    )
                )
                print(
                    "  [DEBUG] Đã phát hiện màn hình Welcome Back. Đang tự động điền mật khẩu..."
                )

                pwd_field.clear()
                pwd_field.send_keys(input_password)
                time.sleep(1)

                sign_in_btn = driver.find_element(
                    By.XPATH, "//button[@type='submit' or contains(text(), 'Sign in')]"
                )
                driver.execute_script("arguments[0].click();", sign_in_btn)
                print("  [DEBUG] Đã bấm Sign in, chờ xác thực...")
                time.sleep(8)

                handle_code_verification(driver)
                handle_cookie_acceptance(driver)

                if "feed" in driver.current_url:
                    print("INFO: Vượt Welcome Back thành công! Đã gia hạn Session mới.")
                    save_cookies(driver)
                    save_credentials(input_username, input_password, CREDENTIALS_FILE)
                    return
                else:
                    print(
                        "  [DEBUG] Vẫn chưa vào được Feed. Chuyển sang đăng nhập thủ công..."
                    )
            except Exception as e:
                print(
                    f"INFO: Không thể vượt Welcome Back ({str(e)[:30]}). Bắt đầu đăng nhập từ đầu..."
                )

            driver.delete_all_cookies()
            time.sleep(2)

    print("INFO: Tiến hành đăng nhập thủ công từ đầu...")
    driver.get("https://www.linkedin.com/login")

    username_field = WebDriverWait(driver, 60).until(
        EC.element_to_be_clickable((By.XPATH, XPATH_USERNAME))
    )
    password_field = WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.XPATH, XPATH_PASSWORD))
    )
    login_button = WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.XPATH, XPATH_LOGIN_BUTTON))
    )

    username_field.clear()
    username_field.send_keys(input_username)
    time.sleep(2)

    password_field.clear()
    password_field.send_keys(input_password)
    time.sleep(2)

    input_username = input_username.strip()

    driver.execute_script("arguments[0].click();", login_button)
    time.sleep(15)

    handle_code_verification(driver)
    handle_cookie_acceptance(driver)

    if "feed" in driver.current_url:
        save_cookies(driver)
        save_credentials(input_username, input_password, CREDENTIALS_FILE)
        print("INFO: Đăng nhập thành công thật sự và đã lưu cookies!")
    else:
        print(
            "❌ LỖI TRẦM TRỌNG: Đăng nhập thất bại! Sai tài khoản/mật khẩu hoặc bị đòi CAPTCHA."
        )
        driver.save_screenshot("login-failed.png")
        raise Exception("Login Failed! Please check your credentials or CAPTCHA.")


login(browser, USERNAME, PASSWORD)


def safe_click(driver, xpath, timeout=5):
    try:
        el = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((By.XPATH, xpath))
        )
        driver.execute_script("arguments[0].click();", el)
        return True
    except TimeoutException:
        return False
    except Exception as e:
        return False


def ensure_top(driver):
    driver.execute_script("window.scrollTo(0, 0)")
    time.sleep(2)


def wait_feed_loaded(driver):
    try:
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.TAG_NAME, "main"))
        )
    except:
        print("Cảnh báo: Không tìm thấy thẻ main, tiếp tục ép chạy...")
        time.sleep(5)


def extract_folder_id(url):
    if not url:
        return None
    match = re.search(r"/folders/([a-zA-Z0-9_-]+)", str(url))
    if match:
        return match.group(1)
    match = re.search(r"/d/([a-zA-Z0-9_-]+)", str(url))
    if match:
        return match.group(1)
    return None


def get_random_image_from_drive(creds, folder_id):
    try:
        drive_service = build("drive", "v3", credentials=creds)
        query = f"'{folder_id}' in parents and mimeType contains 'image/' and trashed = false"
        results = (
            drive_service.files().list(q=query, fields="files(id, name)").execute()
        )
        items = results.get("files", [])

        if not items:
            print(f"  [⚠] Không tìm thấy ảnh nào trong thư mục Drive ID: {folder_id}")
            return None

        random_file = random.choice(items)
        file_id = random_file["id"]
        file_name = random_file["name"]
        print(f"  [+] Đã bốc thăm trúng ảnh: {file_name}")

        request = drive_service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()

        suffix = os.path.splitext(file_name)[1]
        if not suffix:
            suffix = ".png"

        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        temp_file.write(fh.getvalue())
        temp_file.close()

        return temp_file.name
    except Exception as e:
        print("  [❌] Lỗi khi tải ảnh từ Drive:", e)
        return None


def post_to_linkedin(index, driver, screenshot_path):
    local_image_path = None
    post_link = ""

    try:
        actions = ActionChains(driver)
        print("\n===== START POST FLOW =====")

        print("Step 0: Ensure feed loaded...")
        driver.get("https://www.linkedin.com/feed/")
        wait_feed_loaded(driver)
        ensure_top(driver)
        time.sleep(random.uniform(2, 4))

        print("Step 1: Handle popup if exists...")
        popup_xpath = """
        //button[contains(., 'Maybe later')]
        | //button[contains(@aria-label,'Dismiss')]
        | //button[contains(., 'Not now')]
        """
        safe_click(driver, popup_xpath, timeout=3)

        print("Step 2: Click create post...")
        ensure_top(driver)

        start_post_xpath = (
            "//button[contains(@class, 'share-box-feed-entry__trigger')] | "
            "//div[contains(@class, 'share-box-feed-entry__trigger')] | "
            "//button[contains(., 'Start a post')] | "
            "//div[@role='button' and contains(., 'Start a post')]"
        )

        is_modal_opened = False

        try:
            all_triggers = WebDriverWait(driver, 10).until(
                EC.presence_of_all_elements_located((By.XPATH, start_post_xpath))
            )

            valid_triggers = []
            for btn in all_triggers:
                try:
                    if btn.is_displayed() and btn.size["height"] > 0:
                        valid_triggers.append(btn)
                except:
                    pass

            for index_btn, trigger_btn in enumerate(valid_triggers):
                try:
                    driver.execute_script(
                        "arguments[0].scrollIntoView({block: 'center'});", trigger_btn
                    )
                    time.sleep(1)

                    try:
                        ActionChains(driver).move_to_element(
                            trigger_btn
                        ).click().perform()
                    except:
                        driver.execute_script("arguments[0].click();", trigger_btn)

                    WebDriverWait(driver, 3).until(
                        EC.presence_of_element_located(
                            (By.XPATH, "//div[@role='dialog']")
                        )
                    )
                    is_modal_opened = True
                    break
                except:
                    pass

        except Exception as e:
            pass

        if not is_modal_opened:
            driver.save_screenshot("error_step2_modal_failed.png")
            raise Exception(
                "Step 2 Failed: Đã bấm thử mọi nút nhưng LinkedIn chặn mở bảng!"
            )

        time.sleep(2)

        print("Step 3: Find content input area...")
        editor_element = None
        for attempt in range(15):
            js_pierce_shadow = """
            let shadowHost = document.querySelector('#interop-outlet');
            let sharebox = null;
            if (shadowHost && shadowHost.shadowRoot) {
                sharebox = shadowHost.shadowRoot.querySelector('[data-test-modal-id="sharebox"]');
            } else {
                sharebox = document.querySelector('[data-test-modal-id="sharebox"]');
            }
            if (sharebox) {
                let editor = sharebox.querySelector('.ql-editor, [aria-label="Text editor for creating content"]');
                if (editor && editor.getBoundingClientRect().height > 0) {
                    return editor;
                }
            }
            return null;
            """
            editor_element = driver.execute_script(js_pierce_shadow)
            if editor_element:
                break
            time.sleep(1)

        if not editor_element:
            raise Exception("Đã khoan vào Shadow DOM nhưng vẫn không thấy ô soạn thảo.")

        driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center'});", editor_element
        )
        time.sleep(0.5)
        driver.execute_script(
            "arguments[0].focus(); arguments[0].click();", editor_element
        )

        try:
            driver.execute_script(
                "arguments[0].classList.remove('ql-blank');", editor_element
            )
        except:
            pass
        time.sleep(1)

        ActionChains(driver).send_keys(" ").perform()
        time.sleep(1)

        insert_content_area = editor_element

        linkedin_text = df.iloc[index].get("Linkedin content", "")
        linkedin_image_url = df.iloc[index].get("IMAGE", "")
        tags = df.iloc[index].get("TAG", "")
        hashtags = df.iloc[index].get("HASHTAG", "")
        subtags = df.iloc[index].get("SUBTAG", "")
        companies = df.iloc[index].get("COMPANY", "")

        tag_array = ["@" + tag.strip() for tag in str(tags).split(",") if tag.strip()]
        company_array = [
            company.strip() for company in str(companies).split(",") if company.strip()
        ]
        hashtag_string = " ".join(
            ["#" + h.strip() for h in str(hashtags).split(",") if h.strip()]
        )
        subtag_string = " ".join(
            ["#" + s.strip() for s in str(subtags).split(",") if s.strip()]
        )

        print("Step 5: Typing content...")
        time.sleep(random.uniform(1, 2))
        act = ActionChains(driver)

        if hashtag_string:
            human_type(insert_content_area, hashtag_string)
            act.send_keys(Keys.ENTER).perform()
            time.sleep(2)

        paragraphs = linkedin_text.split("\n\n")
        for paragraph in paragraphs:
            human_type(insert_content_area, paragraph)
            time.sleep(random.uniform(1, 2))
            act.send_keys(Keys.ENTER).perform()
            act.send_keys(Keys.ENTER).perform()

        for i in range(len(tag_array)):
            if i < len(company_array):
                text = tag_array[i] + " " + company_array[i]
                human_type(insert_content_area, text)
                time.sleep(4)
                act.send_keys(Keys.DOWN).perform()
                time.sleep(0.5)
                act.send_keys(Keys.ENTER).perform()
                time.sleep(0.5)
                act.send_keys(Keys.ENTER).perform()
                time.sleep(1)

        act.send_keys(Keys.ENTER).perform()

        if subtag_string:
            human_type(insert_content_area, subtag_string)

        time.sleep(3)

        print("Step 6: Processing Image from Drive...")
        folder_id = extract_folder_id(linkedin_image_url)

        if folder_id:
            local_image_path = get_random_image_from_drive(creds, folder_id)

        if local_image_path and os.path.exists(local_image_path):
            print(f"  [DEBUG-STEP 6] Đang tải lên ảnh: {local_image_path}")
            driver.execute_script("""
                let host = document.querySelector('#interop-outlet');
                let root = (host && host.shadowRoot) ? host.shadowRoot : document;
                let dismissBtn = root.querySelector('button[aria-label*="Dismiss preview"]');
                if(dismissBtn) dismissBtn.click();
            """)
            time.sleep(1)

            clicked_media = driver.execute_script("""
                let host = document.querySelector('#interop-outlet');
                let root = (host && host.shadowRoot) ? host.shadowRoot : document;
                let addMediaBtn = root.querySelector('button[aria-label="Add media"]');
                if(addMediaBtn) {
                    addMediaBtn.click();
                    return true;
                }
                return false;
            """)

            if clicked_media:
                time.sleep(2)
                try:
                    file_input = driver.execute_script("""
                        let host = document.querySelector('#interop-outlet');
                        let root = (host && host.shadowRoot) ? host.shadowRoot : document;
                        return root.querySelector('input[type="file"]') || document.querySelector('input[type="file"]');
                    """)
                    file_input.send_keys(local_image_path)
                    print(
                        "  [DEBUG-STEP 6] Đã đẩy file ảnh lên thành công, chờ 5s để load..."
                    )
                    time.sleep(5)

                    driver.execute_script("""
                        let host = document.querySelector('#interop-outlet');
                        let root = (host && host.shadowRoot) ? host.shadowRoot : document;
                        let btns = root.querySelectorAll('button');
                        for(let b of btns) {
                            if(b.innerText.includes('Next') || b.innerText.includes('Done')) {
                                b.click();
                                break;
                            }
                        }
                    """)
                    time.sleep(3)
                except Exception as e:
                    print("  [DEBUG-STEP 6] Lỗi xử lý gửi ảnh:", str(e)[:100])

        print("Step 7: Nhấn nút POST VÀ LẤY LINK TỰ ĐỘNG...")
        time.sleep(2)

        post_success = driver.execute_script("""
            let host = document.querySelector('#interop-outlet');
            let root = (host && host.shadowRoot) ? host.shadowRoot : document;
            let postBtn = root.querySelector('.share-actions__primary-action');
            if (postBtn && !postBtn.disabled) {
                postBtn.click();
                return true;
            }
            return false;
        """)

        if not post_success:
            raise Exception("Không thể nhấn nút Post (Nút bị mờ hoặc không tìm thấy).")

        # ------------------------------------------------------------
        # CẢM BIẾN BẮT LINK ĐÃ ĐƯỢC NÂNG CẤP MẠNH MẼ HƠN
        # ------------------------------------------------------------
        print("  [DEBUG-STEP 7] Đang đứng đợi để tóm gọn link bài viết...")

        # Quét 30 lần, mỗi lần cách nhau 0.5s (Tổng cộng 15 giây chờ đợi)
        for _ in range(30):
            try:
                # Quét mọi thẻ <a> trên trang, tìm thẻ nào có chữ "View post" hoặc "Xem bài"
                link = driver.execute_script("""
                    let toast = document.querySelector('.artdeco-toast-item');
                    if (toast) {
                        let a = toast.querySelector('a');
                        if (a) return a.href;
                    }
                    
                    // Phương án dự phòng: Lùng sục mọi link trên trang có chữ View post
                    let allLinks = document.querySelectorAll('a');
                    for (let i = 0; i < allLinks.length; i++) {
                        let text = allLinks[i].innerText.toLowerCase();
                        if (text.includes('view post') || text.includes('xem bài')) {
                            return allLinks[i].href;
                        }
                    }
                    return '';
                """)
                if link:
                    post_link = link
                    print(f"  ✅ Đã lấy được link bài viết: {post_link}")
                    break
            except:
                pass
            time.sleep(0.5)  # Quét tốc độ cao để bắt kịp Toast notification

        if not post_link:
            print(
                "  ⚠ Đăng thành công nhưng thông báo tắt quá nhanh nên không bắt kịp link."
            )
            post_link = "Thành công (Không lấy kịp link)"

        time.sleep(5)
        print("🎉 XÁC NHẬN: Bài viết đã lên sóng thành công!")

        return "Success", post_link

    except Exception as e:
        print(f"Lỗi: Bài viết chưa được đăng. Chi tiết: {str(e)[:100]}")
        driver.save_screenshot("error_step_final.png")
        return "Failed", ""

    finally:
        if local_image_path and os.path.exists(local_image_path):
            try:
                os.remove(local_image_path)
                print(f"🧹 Đã dọn dẹp xóa ảnh tạm: {local_image_path}")
            except Exception as e:
                pass


"""### **Thực hiện lặp qua các dòng để đăng bài viết với nội dung tương ứng và cập nhật trạng thái, với giới hạn 5 bài đăng mỗi ngày nhằm tránh antibot**"""

post_limit = 4
post_count = 0

for index, row in df.iterrows():
    if post_count >= post_limit:
        print(f"Reached daily limit of {post_limit} posts. Stopping.")
        break

    current_status = str(row.get("Status", "")).strip().capitalize()

    if current_status == "" or current_status == "Failed":
        print(f"Processing row {index}...")

        status, post_link = post_to_linkedin(index, browser, screenshot_path)

        df.at[index, "Status"] = status

        post_count += 1

        if status == "Success":
            df.at[index, "Link bài đã post"] = post_link

            # ------------------------------------------------------------
            # FIX LỖI THỜI GIAN LỆCH MUI GIỜ (SỬA THÀNH GIỜ VIỆT NAM UTC+7)
            # ------------------------------------------------------------
            # Lấy giờ quốc tế (UTC) sau đó cộng thêm 7 tiếng đồng hồ
            vn_time = datetime.datetime.utcnow() + datetime.timedelta(hours=7)
            now_str = vn_time.strftime("%Y-%m-%d %H:%M:%S")

            df.at[index, "Date post"] = now_str

            wait_time = random.randint(30, 60)
            print(f"Post successful. Waiting {wait_time}s before next post...")
            time.sleep(wait_time)
        else:
            print("Post failed. Waiting 15s before retrying...")
            time.sleep(15)
    else:
        print(f"Skipping row {index} (Status: {current_status})")


def update_google_sheet_status(df, spreadsheet_id, range_name):
    values = [df.columns.values.tolist()] + df.values.tolist()
    body = {"values": values}

    result = (
        service.spreadsheets()
        .values()
        .update(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption="RAW",
            body=body,
        )
        .execute()
    )
    print(f"{result.get('updatedCells')} cells updated.")


update_google_sheet_status(df, spreadsheet_ID, range_name)

print("\nĐã xử lý xong toàn bộ bài đăng trong danh sách!")
print("Đang dọn dẹp và đóng trình duyệt Google Chrome...")

try:
    if "browser" in locals() and browser is not None:
        browser.quit()
        print("✅ Đã tắt Google Chrome thành công!")
except Exception as e:
    print(f"⚠ Có lỗi nhẹ khi tắt trình duyệt: {e}")

print("🎉 BOT KẾT THÚC HOẠT ĐỘNG!")
