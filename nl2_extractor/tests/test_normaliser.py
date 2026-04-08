from extractor.normaliser import clean_number, normalise_text

def test_clean_number():
    assert clean_number("1,234.56") == 1234.56
    assert clean_number("1,24,941") == 124941.0
    assert clean_number("(500.00)") == -500.0
    assert clean_number("-") is None
    assert clean_number("Nil") is None
    assert clean_number("3 4,193") == 34193.0
    assert clean_number(None) is None
    assert clean_number(100) == 100.0

def test_normalise_text():
    assert normalise_text("Fire") == "fire"
    assert normalise_text("Marine - Cargo") == "marine - cargo"
    assert normalise_text("Health\nInsurance") == "health insurance"
    assert normalise_text("Workmen's Compensation") == "workmen's compensation"
    assert normalise_text(None) == ""
