"""Fixed settings: departments, university formats and page maths."""

DEPARTMENTS = {
    "Prosthodontics and Crown & Bridge": {
        "short": "Prosthodontics",
        "journals": ["J Prosthet Dent", "J Prosthodont", "Int J Prosthodont", "J Oral Rehabil",
                     "Clin Oral Implants Res", "J Indian Prosthodont Soc", "Int J Oral Maxillofac Implants"],
    },
    "Periodontology": {
        "short": "Periodontology",
        "journals": ["J Periodontol", "J Clin Periodontol", "Periodontol 2000", "J Periodontal Res",
                     "J Indian Soc Periodontol", "Clin Oral Implants Res", "Int J Periodontics Restorative Dent"],
    },
    "Oral and Maxillofacial Surgery": {
        "short": "Oral and Maxillofacial Surgery",
        "journals": ["J Oral Maxillofac Surg", "Int J Oral Maxillofac Surg", "Br J Oral Maxillofac Surg",
                     "J Craniomaxillofac Surg", "J Maxillofac Oral Surg", "Oral Surg Oral Med Oral Pathol Oral Radiol"],
    },
    "Conservative Dentistry and Endodontics": {
        "short": "Conservative Dentistry and Endodontics",
        "journals": ["J Endod", "Int Endod J", "J Conserv Dent", "Oper Dent", "Dent Mater", "J Dent",
                     "Aust Endod J"],
    },
    "Orthodontics and Dentofacial Orthopaedics": {
        "short": "Orthodontics",
        "journals": ["Am J Orthod Dentofacial Orthop", "Angle Orthod", "Eur J Orthod", "Prog Orthod",
                     "Korean J Orthod", "Orthod Craniofac Res", "J Indian Orthod Soc"],
    },
    "Oral and Maxillofacial Pathology and Oral Microbiology": {
        "short": "Oral Pathology",
        "journals": ["J Oral Pathol Med", "Oral Oncol", "Head Neck Pathol", "J Oral Maxillofac Pathol",
                     "Oral Dis", "Oral Surg Oral Med Oral Pathol Oral Radiol"],
    },
    "Public Health Dentistry": {
        "short": "Public Health Dentistry",
        "journals": ["Community Dent Oral Epidemiol", "J Public Health Dent", "Community Dent Health",
                     "BMC Oral Health", "J Indian Assoc Public Health Dent", "Int Dent J"],
    },
    "Paediatric and Preventive Dentistry": {
        "short": "Paediatric and Preventive Dentistry",
        "journals": ["Pediatr Dent", "Int J Paediatr Dent", "Eur Arch Paediatr Dent",
                     "J Indian Soc Pedod Prev Dent", "J Clin Pediatr Dent", "Caries Res"],
    },
    "Oral Medicine and Radiology": {
        "short": "Oral Medicine and Radiology",
        "journals": ["Oral Surg Oral Med Oral Pathol Oral Radiol", "Dentomaxillofac Radiol", "Oral Dis",
                     "J Oral Pathol Med", "Imaging Sci Dent", "J Indian Acad Oral Med Radiol"],
    },
}

# Page layout presets. Each is a starting point: every value can be changed in the app.
UNIVERSITY_PRESETS = {
    "Rajiv Gandhi University of Health Sciences (RGUHS), Karnataka": {
        "university": "Rajiv Gandhi University of Health Sciences, Karnataka, Bengaluru",
        "font": "Times New Roman", "size": 12, "line_spacing": 2.0,
        "margins_cm": (2.54, 2.54, 2.54, 2.54), "page_border": True, "divider_pages": False,
        "header_rule": "993300", "citation_style": "superscript", "page_number_pos": "right",
    },
    "The Tamil Nadu Dr. M.G.R. Medical University, Chennai": {
        "university": "The Tamil Nadu Dr. M.G.R. Medical University, Chennai",
        "font": "Times New Roman", "size": 12, "line_spacing": 2.0,
        "margins_cm": (2.54, 2.54, 2.54, 3.81), "page_border": False, "divider_pages": True,
        "header_rule": "8C1515", "citation_style": "superscript", "page_number_pos": "center",
    },
    "Dr. N.T.R. University of Health Sciences, Andhra Pradesh": {
        "university": "Dr. N.T.R. University of Health Sciences, Vijayawada, Andhra Pradesh",
        "font": "Times New Roman", "size": 12, "line_spacing": 2.0,
        "margins_cm": (2.54, 2.54, 2.54, 2.54), "page_border": True, "divider_pages": True,
        "header_rule": "943634", "citation_style": "superscript", "page_number_pos": "right",
    },
    "Kaloji Narayana Rao University of Health Sciences, Telangana": {
        "university": "Kaloji Narayana Rao University of Health Sciences, Warangal, Telangana",
        "font": "Times New Roman", "size": 12, "line_spacing": 1.5,
        "margins_cm": (2.54, 2.54, 2.54, 3.81), "page_border": True, "divider_pages": False,
        "header_rule": "1F3B5A", "citation_style": "superscript", "page_number_pos": "center",
    },
    "Maharashtra University of Health Sciences (MUHS), Nashik": {
        "university": "Maharashtra University of Health Sciences, Nashik",
        "font": "Times New Roman", "size": 12, "line_spacing": 1.5,
        "margins_cm": (2.54, 2.54, 2.54, 3.81), "page_border": False, "divider_pages": False,
        "header_rule": "1F3B5A", "citation_style": "superscript", "page_number_pos": "center",
    },
    "Other / custom": {
        "university": "",
        "font": "Times New Roman", "size": 12, "line_spacing": 1.5,
        "margins_cm": (2.54, 2.54, 2.54, 3.81), "page_border": False, "divider_pages": False,
        "header_rule": "1F3B5A", "citation_style": "superscript", "page_number_pos": "center",
    },
}

FONTS = ["Times New Roman", "Arial", "Cambria", "Calibri", "Georgia"]


def words_per_page(line_spacing: float, size: int = 12) -> int:
    """Approximate words of body text on one A4 page with ~2.5 cm margins."""
    base = {1.0: 520, 1.15: 460, 1.5: 360, 2.0: 270}
    nearest = min(base, key=lambda k: abs(k - line_spacing))
    return int(base[nearest] * (12 / size) ** 2)


def reference_target(pages: int) -> int:
    return max(8, min(150, round(pages * 0.75)))


def refs_per_page(line_spacing: float) -> int:
    return 12 if line_spacing <= 1.15 else 9 if line_spacing <= 1.5 else 7
