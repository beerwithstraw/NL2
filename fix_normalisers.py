import os
import re

REPO_ROOT = "/Users/pulkit/Desktop/App/extractors"
REPOS = [d for d in os.listdir(REPO_ROOT) if os.path.isdir(os.path.join(REPO_ROOT, d)) and d.startswith("NL")]

def fix_normaliser(repo_name):
    # Determine the target form ID and dashed version
    # repo_name is e.g. "NL2" or "NL43"
    form_num = re.search(r'NL(\d+)', repo_name).group(1)
    form_id = f"NL{form_num}"
    dashed_id = f"NL-{form_num}"
    
    # Path to normaliser.py
    # Expected structure: NL2/nl2_extractor/extractor/normaliser.py
    path = os.path.join(REPO_ROOT, repo_name, f"{repo_name.lower()}_extractor/extractor/normaliser.py")
    if not os.path.exists(path):
        # Try alternate path if any (unlikely given our standard)
        return
        
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
        
    # Standard boilerplate leaks found in audit:
    # 1. "Cell normalisation functions for NL-4 PDF extraction."
    # 2. "# Strings that represent "no value" in NL-4 PDFs"
    # 3. "identical to NL6 normaliser" (seen in NL36)
    
    # We want to replace these with the correct dashed_id or form_id
    
    new_content = content
    # Replace "NL-4" with dashed_id
    new_content = re.sub(r'\bNL-4\b', dashed_id, new_content)
    # Replace "NL4" with form_id
    new_content = re.sub(r'\bNL4\b', form_id, new_content)
    # Replace "NL-6" with dashed_id
    new_content = re.sub(r'\bNL-6\b', dashed_id, new_content)
    # Replace "NL6" with form_id
    new_content = re.sub(r'\bNL6\b', form_id, new_content)
    
    if new_content != content:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"  FIXED: {os.path.relpath(path, REPO_ROOT)}")
    else:
        # print(f"  CLEAN: {os.path.relpath(path, REPO_ROOT)}")
        pass

if __name__ == "__main__":
    print("Standardizing normaliser.py boilerplate across all repos...")
    for repo in sorted(REPOS, key=lambda x: int(re.search(r'NL(\d+)', x).group(1)) if re.search(r'NL(\d+)', x) else 999):
        fix_normaliser(repo)
    print("Done.")
