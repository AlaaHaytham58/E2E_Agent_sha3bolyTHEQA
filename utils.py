import re

def clean_dom(raw_html: str) -> str:
    """
    Cleans the raw HTML to prepare it for LLM consumption.
    (Copied from colleague's code)
    """
    cleaner_html = re.sub(r"", "", raw_html)
    cleaner_html = re.sub(r"<script[\s\S]*?</script>", "", cleaner_html)
    cleaner_html = re.sub(r"<style[\s\S]*?</style>", "", cleaner_html)
    # ... rest of his regex logic ...
    return cleaner_html[:15000] # Increased limit slightly