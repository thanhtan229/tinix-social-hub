"""Facebook selectors live here so UI changes have one repair point."""

import re

LOGIN_EMAIL = "input[name='email'], input#email"
LOGIN_PASSWORD = "input[name='pass'], input#pass"
ACCOUNT_MENU = "[aria-label*='Account' i], [aria-label*='Tài khoản' i], [aria-label*='Your profile' i]"
CHECKPOINT_MARKERS = "form[action*='checkpoint'], [data-pagelet*='Checkpoint'], input[name='approvals_code']"
PAGE_LINKS = "[role='main'] a[href]"
COMPOSER_DIALOG = "[role='dialog']"
COMPOSER_TEXTBOX = "[role='textbox'][contenteditable='true']"
FILE_INPUT = "input[type='file']"
CREATE_POST_NAME = re.compile(
    r"^(Create post|Tạo bài viết|Create a post|Tạo bài đăng|What's on your mind\??|"
    r"Bạn đang nghĩ gì\??|Chia sẻ suy nghĩ[.…]{0,3}|.+\sơi, bạn đang nghĩ gì thế\?)$",
    re.IGNORECASE,
)
POST_BUTTON_NAME = re.compile(r"^(Post|Đăng)$", re.IGNORECASE)
NEXT_BUTTON_NAME = re.compile(r"^(Next|Tiếp)$", re.IGNORECASE)
PAGE_SWITCH_NAME = re.compile(r"^(Switch|Chuyển)$", re.IGNORECASE)
UPLOAD_BUSY = "[aria-label*='Uploading'], [aria-label*='Đang tải'], [role='progressbar']"
SUCCESS_TEXT = re.compile(r"(Your post is now published|Bài viết của bạn đã được đăng|Post published)", re.IGNORECASE)
POST_URL_PARTS = (
    "/posts/",
    "/videos/",
    "/reel/",
    "/permalink.php",
    "/photo/",
)
