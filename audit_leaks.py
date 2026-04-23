import os
import re

REPO_ROOT = "/Users/pulkit/Desktop/App/extractors"
REPOS = [d for d in os.listdir(REPO_ROOT) if os.path.isdir(os.path.join(REPO_ROOT, d)) and d.startswith("NL")]

def check_leaks(repo_name):
    repo_path = os.path.join(REPO_ROOT, repo_name)
    # We want to find references to other NL forms.
    # e.g. in NL2, we look for NL3, NL4, NL5, NL6, NL7, NL34, etc.
    other_forms = []
    for r in REPOS:
        if r == repo_name:
            continue
        # Extract number if possible
        m = re.search(r'NL(\d+)', r)
        if m:
            num = m.group(1)
            other_forms.append(f"NL{num}")
            other_forms.append(f"NL-{num}")
        else:
            other_forms.append(r)
            other_forms.append(r.replace("NL", "NL-"))

    print(f"\n{'='*80}")
    print(f" AUDITING REPO: {repo_name}")
    print(f"{'='*80}")
    
    found_any = False
    
    for root, dirs, files in os.walk(repo_path):
        if any(skip in root for skip in [".git", "__pycache__", ".ipynb_checkpoints", "outputs", "inputs"]):
            continue
            
        for file in files:
            if not file.endswith((".py", ".yaml", ".json", ".txt", ".md")):
                continue
                
            file_path = os.path.join(root, file)
            rel_path = os.path.relpath(file_path, repo_path)
            
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    for i, line in enumerate(lines):
                        for target in other_forms:
                            # Use case-insensitive search with word boundaries
                            # We want to match "NL4" but not "NL2"
                            pattern = r'\b' + re.escape(target) + r'\b'
                            if re.search(pattern, line, re.IGNORECASE):
                                # Special case: ignore if the line also contains the correct NL form (might be a comparison or comment)
                                # Actually, user said "only hits", so let's show it.
                                if not found_any:
                                    found_any = True
                                print(f"  [HIT] {rel_path}:{i+1} -> Found '{target}'")
                                print(f"        Line: {line.strip()}")
                                break # Move to next line once a leak is found in this line
            except Exception as e:
                # print(f"  [ERROR] Could not read {rel_path}: {e}")
                pass
                
    if not found_any:
        print("  CLEAN: No cross-repo references found.")

if __name__ == "__main__":
    # Sort repos numerically
    def repo_key(name):
        m = re.search(r'NL(\d+)', name)
        return int(m.group(1)) if m else 999

    sorted_repos = sorted(REPOS, key=repo_key)
    
    for repo in sorted_repos:
        check_leaks(repo)
    
    print("\nAudit Complete.")
