from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression


# =====================================================
# TRAINING DATA
# =====================================================

texts = [

    # ---------- ROAD ----------
    "large pothole on road",
    "road is damaged and broken",
    "many potholes on street",
    "road has a big hole",
    "damaged road near my house",
    "small pothole on road",
    "road surface is damaged",

    # ---------- GARBAGE ----------
    "garbage is overflowing",
    "waste is not collected",
    "garbage dump on road",
    "too much garbage on street",
    "dustbin is overflowing",
    "garbage near residential area",
    "small amount of garbage",

    # ---------- STREETLIGHT ----------
    "street light is not working",
    "broken streetlight",
    "no light on the road",
    "street lamp is broken",
    "road is dark because streetlight is not working",
    "streetlight needs repair",

    # ---------- WATER ----------
    "water pipe is leaking",
    "water leakage on street",
    "water coming from broken pipe",
    "pipeline is leaking",
    "water is leaking on road",
    "water pipe burst and flooding the road",
    "major water leakage",

    # ---------- DRAINAGE ----------
    "drain is blocked",
    "drainage problem",
    "dirty blocked drainage",
    "drain is overflowing",
    "sewer blockage on road",
    "drain is completely blocked",
    "water is flooding because drain is blocked",

    # ---------- PUBLIC INFRASTRUCTURE ----------
    "public infrastructure is damaged",
    "broken public facility",
    "damaged park equipment",
    "broken public property",
    "public bench is damaged",
    "minor damage to public bench",
    "park equipment is broken"
]


categories = [

    # ROAD
    "Pothole / Damaged Road",
    "Pothole / Damaged Road",
    "Pothole / Damaged Road",
    "Pothole / Damaged Road",
    "Pothole / Damaged Road",
    "Pothole / Damaged Road",
    "Pothole / Damaged Road",

    # GARBAGE
    "Garbage Overflow",
    "Garbage Overflow",
    "Garbage Overflow",
    "Garbage Overflow",
    "Garbage Overflow",
    "Garbage Overflow",
    "Garbage Overflow",

    # STREETLIGHT
    "Broken Streetlight",
    "Broken Streetlight",
    "Broken Streetlight",
    "Broken Streetlight",
    "Broken Streetlight",
    "Broken Streetlight",

    # WATER
    "Water Leakage",
    "Water Leakage",
    "Water Leakage",
    "Water Leakage",
    "Water Leakage",
    "Water Leakage",
    "Water Leakage",

    # DRAINAGE
    "Drainage Issue",
    "Drainage Issue",
    "Drainage Issue",
    "Drainage Issue",
    "Drainage Issue",
    "Drainage Issue",
    "Drainage Issue",

    # INFRASTRUCTURE
    "Damaged Public Infrastructure",
    "Damaged Public Infrastructure",
    "Damaged Public Infrastructure",
    "Damaged Public Infrastructure",
    "Damaged Public Infrastructure",
    "Damaged Public Infrastructure",
    "Damaged Public Infrastructure"
]


# =====================================================
# TRAIN AI MODEL
# =====================================================

vectorizer = TfidfVectorizer(
    lowercase=True,
    ngram_range=(1, 2)
)

X = vectorizer.fit_transform(texts)

model = LogisticRegression(
    max_iter=1000
)

model.fit(X, categories)


# =====================================================
# PRIORITY KEYWORDS
# =====================================================

HIGH_WORDS = [

    "accident",
    "danger",
    "dangerous",
    "emergency",
    "critical",
    "severe",
    "major",
    "flood",
    "flooding",
    "burst",
    "risk",
    "hazard",
    "injury",
    "blocked completely",
    "life threatening"

]


MEDIUM_WORDS = [

    "large",
    "big",
    "broken",
    "damaged",
    "overflow",
    "overflowing",
    "leaking",
    "blocked",
    "pothole",
    "waste",
    "not working",
    "dark",
    "repair",
    "problem"

]


# =====================================================
# PRIORITY FUNCTION
# =====================================================

def calculate_priority(category, description):

    text = description.lower()

    # -----------------------------------------------
    # HIGH PRIORITY
    # -----------------------------------------------

    if any(word in text for word in HIGH_WORDS):

        return "High"


    # -----------------------------------------------
    # CATEGORY BASED PRIORITY
    # -----------------------------------------------

    if category == "Water Leakage":

        if any(word in text for word in [
            "burst",
            "flood",
            "flooding",
            "major",
            "severe"
        ]):

            return "High"

        return "Medium"


    if category == "Drainage Issue":

        if any(word in text for word in [
            "flood",
            "flooding",
            "completely blocked",
            "severe"
        ]):

            return "High"

        return "Medium"


    if category == "Pothole / Damaged Road":

        if any(word in text for word in [
            "accident",
            "danger",
            "dangerous",
            "major",
            "large",
            "big",
            "risk"
        ]):

            return "High"

        return "Medium"


    if category == "Garbage Overflow":

        if any(word in text for word in [
            "overflow",
            "overflowing",
            "large",
            "major",
            "danger"
        ]):

            return "Medium"

        return "Low"


    if category == "Broken Streetlight":

        if any(word in text for word in [
            "danger",
            "accident",
            "dark",
            "road"
        ]):

            return "Medium"

        return "Low"


    if category == "Damaged Public Infrastructure":

        if any(word in text for word in [
            "danger",
            "unsafe",
            "major",
            "severe"
        ]):

            return "High"

        if any(word in text for word in [
            "broken",
            "damaged",
            "repair"
        ]):

            return "Medium"

        return "Low"


    # -----------------------------------------------
    # GENERAL FALLBACK
    # -----------------------------------------------

    if any(word in text for word in MEDIUM_WORDS):

        return "Medium"


    return "Low"


# =====================================================
# MAIN AI ANALYSIS FUNCTION
# =====================================================

def analyze_issue(description):

    # Safety check
    if not description:

        description = "civic issue"


    # -----------------------------------------------
    # AI CATEGORY PREDICTION
    # -----------------------------------------------

    data = vectorizer.transform([description])

    category = model.predict(data)[0]


    # -----------------------------------------------
    # PRIORITY
    # -----------------------------------------------

    priority = calculate_priority(
        category,
        description
    )


    # -----------------------------------------------
    # DEPARTMENT MAPPING
    # -----------------------------------------------

    departments = {

        "Pothole / Damaged Road":
            "Road Department",

        "Garbage Overflow":
            "Sanitation Department",

        "Broken Streetlight":
            "Electrical Department",

        "Water Leakage":
            "Water Supply Department",

        "Drainage Issue":
            "Drainage Department",

        "Damaged Public Infrastructure":
            "Municipal Maintenance Department"

    }


    department = departments.get(
        category,
        "Municipal Corporation"
    )


    return category, priority, department