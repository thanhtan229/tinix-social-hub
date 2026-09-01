"""Facebook selectors live here so UI changes have one repair point."""

LOGIN_EMAIL = "input[name='email'], input#email"
LOGIN_PASSWORD = "input[name='pass'], input#pass"
ACCOUNT_MENU = "[aria-label*='Account'], [aria-label*='Tài khoản'], [aria-label*='Your profile']"
CHECKPOINT_MARKERS = "form[action*='checkpoint'], [data-pagelet*='Checkpoint'], input[name='approvals_code']"
PAGE_LINKS = "a[href]"
COMPOSER_DIALOG = "[role='dialog']"
COMPOSER_TEXTBOX = "[role='textbox'][contenteditable='true']"
FILE_INPUT = "input[type='file']"

