"""Facebook selectors live here so UI changes have one repair point."""

import re

LOGIN_EMAIL = "input[name='email'], input#email"
LOGIN_PASSWORD = "input[name='pass'], input#pass"
ACCOUNT_MENU = "[aria-label*='Account'], [aria-label*='Tài khoản'], [aria-label*='Your profile']"
CHECKPOINT_MARKERS = "form[action*='checkpoint'], [data-pagelet*='Checkpoint'], input[name='approvals_code']"
PAGE_LINKS = "a[href]"
COMPOSER_DIALOG = "[role='dialog']"
COMPOSER_TEXTBOX = "[role='textbox'][contenteditable='true']"
FILE_INPUT = "input[type='file']"
CREATE_POST_NAME = re.compile(r"^(Create post|Tạo bài viết|Create a post|Tạo bài đăng)$", re.IGNORECASE)
POST_BUTTON_NAME = re.compile(r"^(Post|Đăng)$", re.IGNORECASE)
UPLOAD_BUSY = "[aria-label*='Uploading'], [aria-label*='Đang tải'], [role='progressbar']"
SUCCESS_TEXT = re.compile(r"(Your post is now published|Bài viết của bạn đã được đăng|Post published)", re.IGNORECASE)
POST_URL_PARTS = ("/posts/", "/videos/", "/reel/")
