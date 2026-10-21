"""
Derive the structured fields our job API wants (requirements, experience, skills,
benefits, salary, locations) from the free text that public job boards provide.

Everything here is extracted from the listing text; nothing is invented. When a
value can't be found it is left empty/None.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

# ---------- section splitting ----------

REQUIREMENT_HEADINGS = re.compile(
    r"^(requirements?|qualifications?|minimum qualifications|preferred qualifications|"
    r"basic qualifications|what you('|’)ll (bring|need)|what you bring|what we('|’)re looking for|"
    r"who you are|about you|you have|you should have|must[- ]haves?|skills( required| & experience)?|"
    r"key skills|desired skills|eligibility( criteria)?|experience|skills and experience|"
    r"what you need|superpowers|ideal candidate|candidate profile)\b",
    re.I,
)
OTHER_HEADINGS = re.compile(
    r"^(responsibilities|key responsibilities|what you('|’)ll do|the role|about the role|role overview|"
    r"about (us|the team|the company)|who we are|benefits|perks|what we offer|why join|why us|"
    r"compensation|pay|salary|location|equal (employment )?opportunit|our commitment|"
    r"additional information|how to apply|life at)\b",
    re.I,
)


def _is_heading(line: str) -> bool:
    return len(line) <= 80 and not line.endswith(".")


def split_requirements(text: str) -> tuple[str, str]:
    """Return (description_without_requirements, requirements) from plain text."""
    lines = text.split("\n")
    desc, req, mode = [], [], "desc"
    for line in lines:
        stripped = line.strip().rstrip(":").strip()
        if _is_heading(stripped) and REQUIREMENT_HEADINGS.match(stripped):
            mode = "req"
        elif _is_heading(stripped) and OTHER_HEADINGS.match(stripped):
            mode = "desc"
        (req if mode == "req" else desc).append(line)
    return "\n".join(desc).strip(), "\n".join(req).strip()


# ---------- experience ----------

_YEARS = r"(?:years?|yrs?)"
RANGE_RE = re.compile(rf"(\d{{1,2}})\s*\+?\s*(?:-|–|—|to)\s*(\d{{1,2}})\s*\+?\s*{_YEARS}", re.I)
MIN_RE = re.compile(
    rf"(?:(\d{{1,2}})\s*\+\s*{_YEARS}|(?:minimum|min\.?|at least|over)\s*(?:of\s*)?(\d{{1,2}})\s*{_YEARS}|"
    rf"(\d{{1,2}})\s*{_YEARS}\s*(?:of\s*)?(?:relevant\s*|professional\s*|work\s*|hands-on\s*)?experience)",
    re.I,
)


def extract_experience_years(*texts: str) -> tuple[int | None, int | None]:
    for text in texts:
        if not text:
            continue
        m = RANGE_RE.search(text)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            if lo <= hi <= 40:
                return lo, hi
        m = MIN_RE.search(text)
        if m:
            lo = int(next(g for g in m.groups() if g))
            if lo <= 40:
                return lo, None
    return None, None


SOURCE_LEVELS = {
    # SmartRecruiters experienceLevel ids
    "internship": "INTERNSHIP",
    "entry_level": "ENTRY",
    "associate": "ENTRY",
    # "mid_senior_level" is too broad to map; fall through to title/years.
    "director": "EXECUTIVE",
    "executive": "EXECUTIVE",
}


def experience_level(title: str, source_level: str | None, min_years: int | None) -> str:
    t = title.lower()
    if re.search(r"\bintern(ship)?\b", t):
        return "INTERNSHIP"
    if re.search(r"\b(chief|vp|vice president|director|head of|head -|avp|general manager|gm)\b", t):
        return "EXECUTIVE"
    if re.search(r"\b(lead|principal|staff|architect)\b", t):
        return "LEAD"
    # In Indian titles "Senior Executive" / "Account Executive" are junior-to-mid grades.
    executive_grade = "executive" in t and "account executive" not in t
    if re.search(r"\b(senior|sr\.?)\b", t) and not executive_grade:
        return "SENIOR"
    if re.search(r"\b(junior|jr\.?|trainee|fresher|graduate|associate|apprentice)\b", t) or re.search(r"\b(analyst|engineer|developer|specialist|associate) i\b", t):
        return "ENTRY"
    if executive_grade and min_years is None:
        return "ENTRY"
    # SmartRecruiters' "executive" means an executive-grade (junior) role in India
    # when the title doesn't say otherwise, so only trust it for non-"executive" titles.
    level = SOURCE_LEVELS.get((source_level or "").lower())
    if level and not executive_grade and "manager" not in t:
        return level
    if min_years is not None:
        if min_years < 2:
            return "ENTRY"
        if min_years < 5:
            return "MID"
        if min_years < 10:
            return "SENIOR"
        return "LEAD"
    return "MID"


# ---------- skills ----------

SKILLS = [
    # engineering
    "Python", "Java", "JavaScript", "TypeScript", "Go", "Golang", "Kotlin", "Swift", "C++", "C#", "Ruby",
    "Rust", "Scala", "PHP", "SQL", "NoSQL", "React", "React Native", "Angular", "Vue", "Node.js", "Next.js",
    "Spring Boot", "Django", "Flask", "Android", "iOS", "Flutter", "HTML", "CSS", "REST", "GraphQL",
    "Microservices", "AWS", "GCP", "Azure", "Docker", "Kubernetes", "Terraform", "Jenkins", "CI/CD", "Linux",
    "Kafka", "Redis", "PostgreSQL", "MySQL", "MongoDB", "Elasticsearch", "Spark", "Hadoop", "Airflow",
    "Snowflake", "Databricks", "Machine Learning", "Deep Learning", "NLP", "LLM", "Generative AI",
    "TensorFlow", "PyTorch", "Data Science", "Data Analysis", "Data Engineering", "System Design",
    "Distributed Systems", "DevOps", "SRE", "Git", "Selenium", "Automation Testing", "Cybersecurity",
    "Cloud Security", "Information Security",
    # data / business tools
    "Excel", "Power BI", "Tableau", "Looker", "SAP", "Salesforce", "Jira", "Figma", "Google Analytics",
    # business / functional
    "Product Management", "Program Management", "Project Management", "Agile", "Scrum", "Stakeholder Management",
    "Business Development", "Sales", "B2B Sales", "Account Management", "Marketing", "Digital Marketing",
    "SEO", "Performance Marketing", "Content Writing", "Communication", "Negotiation", "Leadership",
    "Team Management", "Operations", "Supply Chain", "Logistics", "Customer Service", "Customer Success",
    "Talent Acquisition", "Recruitment", "HR Business Partnering", "Onboarding", "Payroll",
    "Finance", "Accounting", "Accounts Payable", "Taxation", "GST", "Financial Analysis", "Auditing",
    "Internal Audit", "Risk Management", "Compliance", "Fraud Detection", "Legal", "UI/UX Design",
    "Graphic Design", "Analytics", "Problem Solving",
]
# Names that are also ordinary English words only count when written with their capitalization.
CASE_SENSITIVE_SKILLS = {"Go", "Swift", "Rust", "Spark", "Excel", "Git", "LLM", "REST", "SAP", "Agile", "Vue"}
_SKILL_PATTERNS = [
    (s, re.compile(
        r"(?<![\w+#.])" + re.escape(s).replace(r"\ ", r"[\s-]") + r"(?![\w+#])",
        0 if s in CASE_SENSITIVE_SKILLS or len(s) <= 3 else re.I,
    ))
    for s in SKILLS
]


def extract_skills(requirements: str, description: str, limit: int = 12) -> list[dict]:
    found: list[tuple[str, bool]] = []
    for text, required in ((requirements, True), (description, False)):
        # Descriptions carry company boilerplate; only fall back to them when requirements are thin.
        if not required and len(found) >= 4:
            break
        for name, pattern in _SKILL_PATTERNS:
            if any(name == f[0] for f in found):
                continue
            if text and pattern.search(text):
                found.append((name, required))
    # "Go" alone is too ambiguous unless written as Golang
    found = [f for f in found if f[0] != "Go"]
    return [
        {"skillName": name, "proficiencyLevel": "INTERMEDIATE", "required": required, "orderIndex": i}
        for i, (name, required) in enumerate(found[:limit])
    ]


# ---------- benefits ----------

# benefitType values follow the API enum: HEALTH, STOCK, REMOTE, GYM, FOOD, LEARNING, VISA, BONUS, OTHER.
BENEFITS = [
    ("HEALTH", r"health insurance|medical insurance|mediclaim|health cover|medical cover", "Health insurance"),
    ("HEALTH", r"life insurance|term insurance", "Life insurance"),
    ("STOCK", r"\besops?\b|stock options|equity|\brsus?\b", "Stock options / equity"),
    ("OTHER", r"provident fund|\bpf\b|gratuity|401\(?k\)?|pension", "Provident fund / retirement"),
    ("OTHER", r"paid time off|\bpto\b|paid leave|annual leave|vacation", "Paid time off"),
    ("OTHER", r"parental leave|maternity|paternity", "Parental leave"),
    ("OTHER", r"flexible (working )?hours|flexible schedule|flexi[- ]?time", "Flexible working hours"),
    ("REMOTE", r"work from home|\bwfh\b|remote work|hybrid work", "Remote / hybrid work"),
    ("LEARNING", r"learning (and|&) development|learning budget|training programs?|upskill|certification", "Learning & development"),
    ("GYM", r"\bgym\b|fitness", "Gym / fitness"),
    ("OTHER", r"wellness|wellbeing|well-being|mental health", "Wellness programs"),
    ("FOOD", r"free (meals|lunch|food)|meal (allowance|vouchers)|catered", "Meals"),
    ("OTHER", r"\bcab\b|transport(ation)? (facility|allowance)|commute", "Transport"),
    ("VISA", r"visa sponsorship|relocation", "Visa / relocation support"),
    ("BONUS", r"performance bonus|annual bonus|incentives?", "Performance bonus / incentives"),
]


def extract_benefits(text: str) -> list[dict]:
    return [
        {"benefitType": btype, "description": desc}
        for btype, pattern, desc in BENEFITS
        if re.search(pattern, text or "", re.I)
    ]


# ---------- salary ----------

_UNIT = {"l": 100_000, "lakh": 100_000, "lakhs": 100_000, "lpa": 100_000, "cr": 10_000_000, "k": 1_000}
INR_RANGE = re.compile(
    r"(?:₹|(?<![a-z])(?:inr|rs\.?))\s*(\d[\d,.]*)\s*(lakhs?|lpa|l|cr|k)?\b\s*(?:-|–|to)\s*(?:₹|(?<![a-z])(?:inr|rs\.?))?\s*(\d[\d,.]*)\s*(lakhs?|lpa|l|cr|k)?\b"
    r"|(\d[\d.]*)\s*(?:-|–|to)\s*(\d[\d.]*)\s*(lpa|lakhs?)\b",
    re.I,
)


def _amount(num: str, unit: str | None) -> int:
    return int(float(num.replace(",", "")) * _UNIT.get((unit or "").lower(), 1))


def extract_salary(text: str) -> dict | None:
    m = INR_RANGE.search(text or "")
    if not m:
        return None
    if m.group(1):
        unit = m.group(4) or m.group(2)
        lo, hi = _amount(m.group(1), m.group(2) or unit), _amount(m.group(3), unit)
    else:
        lo, hi = _amount(m.group(5), m.group(7)), _amount(m.group(6), m.group(7))
    if not (0 < lo <= hi):
        return None
    period = "MONTHLY" if hi < 500_000 and re.search(r"per month|/month|monthly|stipend", text, re.I) else "YEARLY"
    return {"salaryMin": lo, "salaryMax": hi, "salaryCurrency": "INR", "salaryPeriod": period}


# ---------- locations ----------

INDIA_CITIES = {
    "new delhi": ("New Delhi", "Delhi"), "delhi": ("New Delhi", "Delhi"),
    "gurugram": ("Gurugram", "Haryana"), "gurgaon": ("Gurugram", "Haryana"),
    "greater noida": ("Greater Noida", "Uttar Pradesh"), "noida": ("Noida", "Uttar Pradesh"),
    "faridabad": ("Faridabad", "Haryana"), "ghaziabad": ("Ghaziabad", "Uttar Pradesh"),
    "bengaluru": ("Bengaluru", "Karnataka"), "bangalore": ("Bengaluru", "Karnataka"),
    "mumbai": ("Mumbai", "Maharashtra"), "pune": ("Pune", "Maharashtra"),
    "hyderabad": ("Hyderabad", "Telangana"), "chennai": ("Chennai", "Tamil Nadu"),
    "kolkata": ("Kolkata", "West Bengal"), "ahmedabad": ("Ahmedabad", "Gujarat"),
    "jaipur": ("Jaipur", "Rajasthan"), "chandigarh": ("Chandigarh", "Chandigarh"),
    "lucknow": ("Lucknow", "Uttar Pradesh"), "indore": ("Indore", "Madhya Pradesh"),
    "kochi": ("Kochi", "Kerala"), "coimbatore": ("Coimbatore", "Tamil Nadu"),
}
COUNTRY_CODES = {"in": "India", "india": "India", "us": "United States", "gb": "United Kingdom", "sg": "Singapore", "ae": "United Arab Emirates"}


def parse_location(raw: str, country_code: str | None = None, remote: bool | None = None) -> dict:
    text = (raw or "").strip()
    lower = text.lower()
    is_remote = bool(remote) or "remote" in lower or "work from home" in lower
    for key, (city, state) in INDIA_CITIES.items():
        if re.search(rf"\b{key}\b", lower):
            return {"raw": text, "city": city, "state": state, "country": "India", "remote": is_remote}
    parts = [p.strip() for p in text.split(",") if p.strip()]
    city = state = country = None
    if len(parts) >= 3:
        city, state, country = parts[0], parts[1], parts[-1]
    elif len(parts) == 2:
        city, country = parts
    elif len(parts) == 1 and not is_remote:
        city = parts[0]
    country = COUNTRY_CODES.get((country_code or "").lower()) or country
    if re.search(r"\b(india|भारत)\b", text, re.I):
        country = "India"
    return {"raw": text, "city": city, "state": state, "country": country, "remote": is_remote}


# ---------- company ----------


def logo_from_website(website: str) -> str:
    domain = urlparse(website).netloc if website else ""
    return f"https://www.google.com/s2/favicons?domain={domain}&sz=128" if domain else ""


def enrich(record: dict, source_level: str | None = None) -> dict:
    """Fill structured fields on a collected record in place."""
    if not record.get("requirements"):
        record["description"], record["requirements"] = split_requirements(record["description"])
    full_text = f"{record['description']}\n{record['requirements']}"
    lo, hi = extract_experience_years(record["requirements"], record["description"])
    record["experienceMinYears"], record["experienceMaxYears"] = lo, hi
    record["experienceLevel"] = experience_level(record["title"], source_level, lo)
    record["skills"] = extract_skills(record["requirements"], record["description"])
    record["benefits"] = extract_benefits(full_text)
    if not record.get("salaryMin"):
        salary = extract_salary(full_text)
        if salary:
            record.update(salary, salaryVisible=True)
    if record.get("externalCompanyWebsite") and not record.get("externalCompanyLogoUrl"):
        record["externalCompanyLogoUrl"] = logo_from_website(record["externalCompanyWebsite"])
    return record
