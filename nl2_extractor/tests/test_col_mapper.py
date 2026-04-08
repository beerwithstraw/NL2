from extractor.col_mapper import jaccard_similarity, build_column_map

def test_jaccard_similarity():
    # Exact match
    assert jaccard_similarity("fire", "fire") == 1.0
    
    # Subset boost (Item 1 Phase 3 Assertion)
    # 'fire insurance' (2 words) vs 'fire' (1 word). intersection=1, union=2. jaccard=0.5. 
    # overlap=1.0. boost = (0.5 + 1.0)/2 = 0.75.
    assert jaccard_similarity("fire insurance", "fire") == 0.75
    assert jaccard_similarity("fire insurance", "fire") > 0.60
    
    # Low similarity (Item 3 Phase 3 Assertion)
    # 'workmens compensation' vs 'motor od'. No common words.
    assert jaccard_similarity("workmens compensation", "motor od") == 0.0
    assert jaccard_similarity("workmens compensation", "motor od") < 0.60

def test_build_column_map_heuristic():
    # Mock table with headers
    table = [
        ["Particulars", "Fire", "Fire", "Marine", "Marine"],
        ["", "Up to Q1", "Up to Q1 PY", "Up to Q1", "Up to Q1 PY"],
        ["LOB 1", "100", "50", "200", "150"],
        ["LOB 2", "200", "100", "400", "300"]
    ]
    # Fire should map to fire, Marine to total_marine (if alias matches)
    col_map = build_column_map(table, "generic")
    
    # Check if fire was mapped (col 1 and 2)
    assert col_map[1]["lob"] == "fire"
    assert col_map[1]["period"] == "qtr"
    assert col_map[2]["lob"] == "fire"
    assert col_map[2]["period"] == "ytd"
