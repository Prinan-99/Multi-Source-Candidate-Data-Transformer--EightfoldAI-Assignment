"""
Canonical skill normalisation.

Maps common aliases / misspellings / capitalisation variants to a single
canonical skill name. Anything not in the map is title-cased and returned
as-is (unknown skills are preserved, never dropped).
"""

from __future__ import annotations

_SKILL_ALIASES: dict[str, str] = {
    # Python ecosystem
    "python": "Python", "python3": "Python", "py": "Python",
    "django": "Django", "flask": "Flask", "fastapi": "FastAPI",
    "pandas": "Pandas", "numpy": "NumPy", "numpy": "NumPy",
    "scikit-learn": "scikit-learn", "sklearn": "scikit-learn",
    "tensorflow": "TensorFlow", "tf": "TensorFlow",
    "pytorch": "PyTorch", "torch": "PyTorch",
    "keras": "Keras",

    # JS/TS
    "javascript": "JavaScript", "js": "JavaScript",
    "typescript": "TypeScript", "ts": "TypeScript",
    "react": "React", "reactjs": "React", "react.js": "React",
    "vue": "Vue.js", "vuejs": "Vue.js", "vue.js": "Vue.js",
    "angular": "Angular", "angularjs": "Angular",
    "node": "Node.js", "nodejs": "Node.js", "node.js": "Node.js",
    "next": "Next.js", "nextjs": "Next.js", "next.js": "Next.js",

    # Data / ML
    "machine learning": "Machine Learning", "ml": "Machine Learning",
    "deep learning": "Deep Learning", "dl": "Deep Learning",
    "nlp": "NLP", "natural language processing": "NLP",
    "computer vision": "Computer Vision", "cv": "Computer Vision",
    "data science": "Data Science",
    "data analysis": "Data Analysis",
    "sql": "SQL", "mysql": "MySQL", "postgresql": "PostgreSQL",
    "postgres": "PostgreSQL", "sqlite": "SQLite",
    "mongodb": "MongoDB", "mongo": "MongoDB",
    "redis": "Redis",

    # Cloud / DevOps
    "aws": "AWS", "amazon web services": "AWS",
    "gcp": "GCP", "google cloud": "GCP", "google cloud platform": "GCP",
    "azure": "Azure", "microsoft azure": "Azure",
    "docker": "Docker", "kubernetes": "Kubernetes", "k8s": "Kubernetes",
    "terraform": "Terraform", "ansible": "Ansible",
    "ci/cd": "CI/CD", "cicd": "CI/CD",
    "git": "Git", "github": "GitHub", "gitlab": "GitLab",
    "linux": "Linux", "bash": "Bash", "shell": "Shell Scripting",

    # Languages
    "java": "Java", "c++": "C++", "cpp": "C++",
    "c#": "C#", "csharp": "C#", "go": "Go", "golang": "Go",
    "rust": "Rust", "scala": "Scala", "kotlin": "Kotlin",
    "swift": "Swift", "ruby": "Ruby", "php": "PHP",
    "r": "R", "matlab": "MATLAB",

    # Other
    "rest": "REST APIs", "rest api": "REST APIs", "restful": "REST APIs",
    "graphql": "GraphQL", "grpc": "gRPC",
    "agile": "Agile", "scrum": "Scrum",
    "llm": "LLMs", "llms": "LLMs",
    "rag": "RAG",
    "prompt engineering": "Prompt Engineering",
}


def canonicalise_skill(raw: str) -> str:
    """Return the canonical name for a skill string."""
    if not raw:
        return raw
    lookup = raw.strip().lower()
    return _SKILL_ALIASES.get(lookup, raw.strip().title())


def canonicalise_skill_list(raw_skills: list[str]) -> list[str]:
    """Canonicalise and deduplicate a list of skill strings."""
    seen: set[str] = set()
    result: list[str] = []
    for s in raw_skills:
        c = canonicalise_skill(s)
        if c and c not in seen:
            seen.add(c)
            result.append(c)
    return result
