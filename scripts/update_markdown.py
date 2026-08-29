import sys
from pathlib import Path

def main():
    cluster_tsv = Path("scripts/flair_clusters.tsv")
    keywords_md = Path("en_us/keywords.md")
    new_ids_tsv = Path("scripts/new_discovered_ids.tsv")
    
    # 1. Find the redundant keywords
    redundant_keywords = set()
    if cluster_tsv.exists():
        for line in cluster_tsv.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) >= 4:
                keyword = parts[2]
                redundant_tail = parts[3]
                if redundant_tail == "yes":
                    redundant_keywords.add(keyword.lower())

    # 2. Find the new discovered IDs
    new_ids = set()
    if new_ids_tsv.exists():
        for line in new_ids_tsv.read_text(encoding="utf-8").splitlines():
            if line.startswith("id\t") or not line.strip():
                continue
            new_id = line.split("\t")[0]
            new_ids.add(new_id)

    # 3. Read current keywords.md
    lines = keywords_md.read_text(encoding="utf-8").splitlines()
    
    header = []
    current_keywords = []
    
    for line in lines:
        if line.startswith("See [") or line.strip() == "":
            if not current_keywords:
                header.append(line)
        else:
            current_keywords.append(line.strip())

    # 4. Filter current keywords to remove redundant ones
    filtered_keywords = []
    for kw in current_keywords:
        if kw.lower() not in redundant_keywords:
            filtered_keywords.append(kw)

    # 5. Add new discovered IDs
    # Convert filtered_keywords to lower to avoid adding duplicates
    existing_lower = {kw.lower() for kw in filtered_keywords}
    for new_id in new_ids:
        if new_id.lower() not in existing_lower:
            filtered_keywords.append(new_id)

    # 6. Sort alphabetically (case-insensitive)
    filtered_keywords.sort(key=lambda x: x.lower())

    # 7. Write back to keywords.md
    with keywords_md.open("w", encoding="utf-8") as f:
        for h in header:
            f.write(h + "\n")
        
        for i, kw in enumerate(filtered_keywords):
            f.write(kw + "\n")
            if i < len(filtered_keywords) - 1:
                f.write("\n")

    print(f"Removed {len(current_keywords) - len(filtered_keywords) + len(new_ids)} redundant keywords.")
    print(f"Added {len(new_ids)} new keywords.")
    print(f"Total keywords now: {len(filtered_keywords)}")

if __name__ == "__main__":
    main()
