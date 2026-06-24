"""Verify i18n module"""
import sys
sys.path.insert(0, r'C:\Users\35515\.qclaw\workspace-tfxjjhfnjialcuju\jinli-ai')
from i18n import _, set_language, get_available_languages

print("Languages:", get_available_languages())
set_language('zh')
print("zh app_name:", _('app_name'))
set_language('en')
print("en app_name:", _('app_name'))
print("OK")
