"""Profile-specific resume generation prompts and helpers."""

import re

PROFILES = {
    "data analyst": {
        "keywords": ["sql", "power bi", "tableau", "excel", "python", "pandas", "numpy",
                     "dashboard", "visualization", "analytics", "kpi", "reporting"],
        "summary_focus": "data analytics, dashboarding, business intelligence",
        "skill_order": ["Data Analytics", "Visualization & Reporting", "AI / ML & GenAI", "Other Skills"],
    },
    "business intelligence analyst": {
        "keywords": ["power bi", "tableau", "sql", "dashboard", "reporting", "visualization",
                     "etl", "data modeling", "kpi", "business intelligence", "analytics"],
        "summary_focus": "business intelligence, dashboard development, data-driven decision making",
        "skill_order": ["Visualization & Reporting", "Data Analytics", "AI / ML & GenAI", "Other Skills"],
    },
    "financial analyst": {
        "keywords": ["financial analysis", "fp&a", "budgeting", "forecasting", "excel",
                     "financial statements", "variance analysis", "profitability", "cash flow"],
        "summary_focus": "financial analysis, FP&A, budgeting, forecasting",
        "skill_order": ["Finance & Accounting", "Data Analytics", "Visualization & Reporting", "Other Skills"],
    },
    "finance": {
        "keywords": ["financial analysis", "fp&a", "budgeting", "forecasting", "excel",
                     "financial statements", "accounting", "taxation", "sap"],
        "summary_focus": "finance, accounting, financial planning and analysis",
        "skill_order": ["Finance & Accounting", "Data Analytics", "Visualization & Reporting", "Other Skills"],
    },
    "sap fico": {
        "keywords": ["sap", "sap fico", "sap s4 hana", "sap sac", "financial accounting",
                     "controlling", "finance", "accounting"],
        "summary_focus": "SAP FICO, SAP S4 HANA, financial systems",
        "skill_order": ["SAP & ERP", "Finance & Accounting", "Data Analytics", "Other Skills"],
    },
    "ai engineer": {
        "keywords": ["llm", "rag", "langchain", "crewai", "vector database", "chroma",
                     "huggingface", "python", "groq", "agentic ai", "prompt engineering"],
        "summary_focus": "AI engineering, LLMs, RAG systems, agentic AI",
        "skill_order": ["AI / ML & GenAI", "Programming", "Data Analytics", "Other Skills"],
    },
    "agentic ai engineer": {
        "keywords": ["crewai", "langgraph", "multi-agent", "agent orchestration", "llm",
                     "tool use", "autonomous systems", "python", "groq"],
        "summary_focus": "agentic AI, multi-agent systems, LLM orchestration",
        "skill_order": ["AI / ML & GenAI", "Agentic AI", "Programming", "Other Skills"],
    },
    "machine learning engineer": {
        "keywords": ["machine learning", "python", "pandas", "numpy", "scikit-learn",
                     "deep learning", "transformers", "huggingface", "mlops"],
        "summary_focus": "machine learning, predictive modeling, ML pipelines",
        "skill_order": ["AI / ML & GenAI", "Programming", "Data Analytics", "Other Skills"],
    },
    "genai": {
        "keywords": ["generative ai", "llm", "rag", "langchain", "prompt engineering",
                     "gpt", "llama", "groq", "vector database", "chroma"],
        "summary_focus": "generative AI, LLMs, RAG, prompt engineering",
        "skill_order": ["AI / ML & GenAI", "Programming", "Data Analytics", "Other Skills"],
    },
    "llm": {
        "keywords": ["llm", "large language models", "rag", "langchain", "prompt engineering",
                     "fine-tuning", "vector database", "chroma", "huggingface", "groq"],
        "summary_focus": "large language models, RAG, LLM application development",
        "skill_order": ["AI / ML & GenAI", "Programming", "Data Analytics", "Other Skills"],
    },
}


def detect_profile(job_title: str, job_description: str, category: str = "") -> str:
    """Detect the best-matching profile for a job.

    Uses title matching first (strongest signal), then keyword scoring
    with tie-breaking toward more specific profiles.
    """
    title_lower = job_title.lower()
    text = f"{title_lower} {category} {job_description}".lower()

    import re
    title_variants = {
        "genai": [r'\bgenai\b', r'\bgenerative\s+ai\b'],
        "llm": [r'\bllm\b', r'\blarge\s+language\s+model'],
        "sap fico": [r'\bsap\s+fico\b'],
        "agentic ai engineer": [r'\bagentic\s+ai\b'],
        "ai engineer": [r'\bai\s+engineer\b'],
        "machine learning engineer": [r'\bmachine\s+learning\b', r'\bml\s+engineer\b'],
        "business intelligence analyst": [r'\bbusiness\s+intelligence\b', r'\bbi\s+analyst\b'],
        "financial analyst": [r'\bfinancial\s+analyst\b'],
        "data analyst": [r'\bdata\s+analyst\b'],
        "finance": [r'\bfinance\b'],
    }

    title_exact_matches = {}
    for profile, patterns in title_variants.items():
        for pat in patterns:
            if re.search(pat, title_lower):
                title_exact_matches[profile] = True
                break

    if title_exact_matches:
        profile_order = [
            "agentic ai engineer", "genai", "llm", "ai engineer",
            "machine learning engineer",
            "sap fico", "financial analyst", "finance",
            "business intelligence analyst", "data analyst",
        ]
        for p in profile_order:
            if p in title_exact_matches:
                return p
        return list(title_exact_matches.keys())[0]

    scores = {}
    for profile, config in PROFILES.items():
        score = sum(3 if kw in title_lower else (2 if kw in text else 0) for kw in config["keywords"])
        scores[profile] = score

    best_score = max(scores.values())
    if best_score == 0:
        return "data analyst"

    candidates = [p for p, s in scores.items() if s == best_score]
    if len(candidates) == 1:
        return candidates[0]

    preference_order = [
        "agentic ai engineer", "ai engineer", "machine learning engineer",
        "genai", "llm", "sap fico", "finance", "financial analyst",
        "business intelligence analyst", "data analyst",
    ]
    for preferred in preference_order:
        if preferred in candidates:
            return preferred
    return candidates[0]


PROJECTS_DATA = [
    {
        "title": "Agentic AI — Multi-Agent Newsletter Generator",
        "description": ("Built an autonomous multi-agent system using CrewAI where 3 AI agents "
                        "(Researcher, Writer, Proofreader) collaborate to research, write, and "
                        "proofread newsletter articles end-to-end."),
        "impact": "Demonstrates production-ready agent orchestration with live web search integration and automated content generation pipeline.",
        "technologies": "Python, CrewAI, Groq LLM, LiteLLM, SerperDev API",
        "url": "https://github.com/heenakausher/Agentic-AI"
    },
    {
        "title": "AI Chatbot RAG — Retrieval-Augmented Generation Chatbot",
        "description": ("Implemented a 3-phase RAG chatbot with Streamlit frontend: basic chatbot, "
                        "LLM-powered conversational agent, and PDF-based Q&A system using "
                        "retrieval-augmented generation."),
        "impact": "Enables users to upload PDFs and ask natural language questions over document content using semantic search and LLM generation.",
        "technologies": "Python, LangChain, Streamlit, Groq LLM, HuggingFace Embeddings, Chroma DB",
        "url": "https://github.com/heenakausher/ai-chatbot-rag"
    },
    {
        "title": "AI Jobs Agent — Automated Job Application Pipeline",
        "description": ("Built a fully automated job scraping, AI scoring, and tailored resume/cover "
                        "letter generation system with Google Sheets integration and GitHub Actions CI/CD."),
        "impact": "Automates the entire job application workflow from discovery to tailored application materials at scale.",
        "technologies": "Python, Groq LLM, CrewAI, GitHub Actions, Google Sheets API, DOCX/PDF Generation",
        "url": "https://github.com/heenakausher/AI-Jobs-Agent"
    },
    {
        "title": "GitHub Actions CI/CD Pipeline",
        "description": ("Implemented automated CI/CD workflows for Python applications including "
                        "testing, linting, and deployment using GitHub Actions."),
        "impact": "Established automated quality assurance and deployment pipeline following DevOps best practices.",
        "technologies": "GitHub Actions, YAML, Python, CI/CD",
        "url": "https://github.com/heenakausher/apptestgithubaction"
    },
]


def _get_relevant_projects(profile: str, max_projects: int = 4) -> list:
    """Get the most relevant projects for a given profile, preserving factual accuracy."""
    if profile in ("ai engineer", "agentic ai engineer", "machine learning engineer", "genai", "llm"):
        return PROJECTS_DATA[:max_projects]
    return PROJECTS_DATA[:max_projects]


def build_system_prompt(profile: str, cv_text: str) -> str:
    """Build the profile-specific system prompt for resume generation."""

    profile_config = PROFILES.get(profile, PROFILES["data analyst"])
    projects = _get_relevant_projects(profile)
    projects_text = _format_projects_for_prompt(projects)

    return f"""You are an expert ATS optimization specialist, professional resume writer, and career coach. Your task is to produce 4 items for a job application using the delimiters shown below.

PROFILE FOCUS: {profile_config['summary_focus']}

STRICT RULES — Violations will result in rejection:
1. NEVER invent or fabricate ANY information: projects, companies, experience, internships, certifications, awards, dates, achievements, metrics, skills, GitHub URLs, LinkedIn URLs, or portfolio URLs.
2. Only rephrase, reorganize, restructure, de-emphasize, or emphasize information that already exists in the candidate's profile.
3. NEVER fabricate numbers or metrics. Only use quantified achievements if they appear in the original profile.
4. NEVER generate placeholder links or fictional repository URLs.
5. Keep all dates, company names, percentages, and factual data exactly as in the original.
6. If information is unavailable, omit it. Do NOT guess. Do NOT infer. Do NOT fabricate.
7. Prioritize relevance to the target role — emphasize matching skills/experience and de-emphasize irrelevant sections.
8. Maximum 2 pages when formatted.
9. Every bullet must start with strong action verbs (Developed, Automated, Designed, Built, Optimized, Reduced, Improved, Led, Implemented, Engineered).
10. Use STAR/CAR principles for experience bullets.
11. Skills must be organized into categories. Only include skills supported by the candidate profile.

ATS OPTIMIZATION RULES:
- No tables, text boxes, icons, graphics, columns, or headers/footers with important info
- Use standard section headings: PROFESSIONAL SUMMARY, TECHNICAL SKILLS, WORK EXPERIENCE, GITHUB PROJECTS, EDUCATION, CERTIFICATIONS
- Maximize keyword matching without keyword stuffing
- Use consistent formatting throughout

Use these exact delimiters:

===TAILORED_CV===
Heena Kausher
kausher92@gmail.com | 7898680077 | www.github.com/heenakausher
www.linkedin.com/in/heena-kausher-90418a118 | www.mygreatlearning.com/eportfolio/heena-kausher

PROFESSIONAL SUMMARY
<3-5 line professional summary tailored to the target role. Must be role-specific, contain ATS keywords, sound natural, and never be generic.>

TECHNICAL SKILLS
<Organize into categories based on profile focus. Example format:>
<Category Name>:
- Skill 1
- Skill 2

WORK EXPERIENCE
<Company Name> — <Date Range>
<Title>
- <Action verb bullet point with STAR/CAR format>
- <Quantified achievement when available>

GITHUB PROJECTS
{projects_text}

EDUCATION
- MBA - Banking & Finance, NMIMS CDOE | 67.33%
- M.Com - Pt. Ravishankar Shukla University | 46.50%
- B.Com - Pt. Ravishankar Shukla University | 60.44%

CERTIFICATIONS
- PGP in Data Science & Analytics - Great Lakes Executive Learning | GPA: 3.9
- Chartered Accountancy - IPCC (Group-1) | May 2012 | 52.75%
- Chartered Accountancy - CPT | Dec 2010 | 55.00%

===COVER_LETTER===
<Professional cover letter, 300-450 words, personalized to company, role, and job description. Avoid clichés and generic AI wording.>

===INTERVIEW_PREP===
<Comma-separated list of technical and behavioural topics to prepare for this role>

===ACCEPTANCE_CHANCE===
<Number 0-100 representing estimated probability of acceptance>

CANDIDATE'S ORIGINAL PROFILE (use ONLY this information):
{cv_text}"""


def _format_projects_for_prompt(projects: list) -> str:
    """Format project data for inclusion in the system prompt."""
    lines = []
    for i, proj in enumerate(projects, 1):
        lines.append(f"Project {i}: {proj['title']}")
        lines.append(f"Technologies: {proj['technologies']}")
        lines.append(f"- {proj['description']}")
        lines.append(f"- {proj['impact']}")
        lines.append(f"GitHub: {proj['url']}")
    return "\n".join(lines)


def build_cover_letter_prompt(profile: str, job: dict, cv_text: str) -> str:
    """Build a focused prompt for just the cover letter."""
    profile_config = PROFILES.get(profile, PROFILES["data analyst"])
    return f"""You are a professional cover letter writer specializing in {profile_config['summary_focus']} roles.

Write a professional, concise cover letter (300-450 words) for the following job application.

TARGET JOB:
Title: {job['title']}
Company: {job['company']}
Location: {job['location']}
Category: {job.get('category', 'N/A')}

JOB DESCRIPTION:
{job.get('description', 'Not available')}

CANDIDATE PROFILE:
{cv_text}

RULES:
- 300-450 words
- Personalized to the specific company and role
- Reference specific skills and experience from the profile
- Avoid clichés ("I am writing to apply", "I am excited to", etc.)
- Avoid generic AI wording
- Professional but conversational tone
- Show, don't tell — use specific examples
- End with a clear call to action"""


def build_review_prompt() -> str:
    """Build the system prompt for resume quality review."""
    return """You are an expert resume reviewer and quality assurance specialist. Your task is to review the following tailored resume and verify:

1. GRAMMAR & TYPO: Check for spelling errors, grammar issues, punctuation mistakes
2. PROFESSIONAL TONE: Ensure language is professional and appropriate
3. ATS KEYWORD COVERAGE: Verify relevant keywords from the job description are naturally incorporated
4. HALLUCINATIONS: Flag any information that appears fabricated or not supported by the candidate profile
5. DUPLICATE CONTENT: Flag any repeated phrases or redundant bullet points
6. WEAK BULLET POINTS: Identify bullets that lack action verbs or measurable impact
7. ACTION VERBS: Verify bullets start with strong action verbs
8. CONSISTENCY: Check formatting consistency throughout

For each issue found, provide:
- Location in the resume
- Description of the issue
- Suggested fix

After the review, output the FULL IMPROVED VERSION of the resume with all issues corrected.

Use this format:

===REVIEW===
<One paragraph summary of overall quality>

Issues Found:
1. [Location]: [Issue] → [Fix]

===IMPROVED_CV===
<Complete improved resume with all issues resolved>

Rules:
- Do NOT change factual information
- Do NOT add fabricated achievements
- Do NOT invent projects or experience
- Only fix issues you identified in the review
- Maintain the same section structure and formatting"""


def extract_delimited(text: str, label: str) -> str:
    """Extract content between ===LABEL=== and the next === delimiter."""
    start = text.find(f"==={label}===")
    if start == -1:
        return ""
    start += len(f"==={label}===")
    remaining = ["TAILORED_CV", "COVER_LETTER", "INTERVIEW_PREP", "ACCEPTANCE_CHANCE", "IMPROVED_CV"]
    end = len(text)
    for other in remaining:
        if other == label:
            continue
        pos = text.find(f"==={other}===", start)
        if pos != -1 and pos < end:
            end = pos
    return text[start:end].strip()


def extract_score(text: str) -> int:
    """Extract numeric score from acceptance chance text."""
    import re
    match = re.search(r'\b(\d{1,3})\b', text)
    if match:
        num = int(match.group(1))
        return max(0, min(100, num))
    try:
        num = int("".join(c for c in text if c.isdigit()))
        return max(0, min(100, num))
    except (ValueError, TypeError):
        return 50
