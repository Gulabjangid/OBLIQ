# Genarateata.py
import json
import random

def generate_mock_data():
    first_names = ["Rahul", "Anita", "Kiran", "Sameer", "Priya", "Amit", "Neha", "Vikram", "Pooja", "Suresh"]
    last_names = ["Sharma", "Verma", "Mehta", "Joshi", "Nair", "Patel", "Singh", "Reddy", "Gupta", "Desai"]
    company_prefixes = ["Apex", "Zenith", "BlueShift", "Quantum", "Nexus", "Stellar", "Nova", "Prime", "Vertex", "Omega"]
    company_suffixes = ["Cloud Technologies", "Logistics", "Exports", "Healthcare", "FinTech", "Consulting", "Industries", "Retail", "Enterprises", "Solutions"]
    entity_types = ["Private Limited", "Partnership Firm", "LLP", "Proprietorship"]
    
    document_templates = [
        {"name": "July 2026 Bank Statement", "due": "2026-08-20"},
        {"name": "GSTR-2B Reconciliation", "due": "2026-08-22"},
        {"name": "Sales Invoice Register", "due": "2026-08-15"},
        {"name": "Q1 TDS Challan 281", "due": "2026-07-31"},
        {"name": "Form 16A Vendor Summary", "due": "2026-08-12"},
        {"name": "Cash Expense Vouchers", "due": "2026-08-14"},
        {"name": "Director KYC Form DIR-3", "due": "2026-08-24"},
        {"name": "Professional Tax Challans", "due": "2026-08-10"}
    ]
    
    deadline_templates = [
        {"event": "GSTR-3B Monthly Filing", "date": "2026-08-20", "criticality": "High"},
        {"event": "TDS Deposit (July)", "date": "2026-08-07", "criticality": "Medium"},
        {"event": "ROC DIR-3 KYC", "date": "2026-08-30", "criticality": "Urgent"},
        {"event": "Advance Tax Installment (Q2)", "date": "2026-09-15", "criticality": "High"},
        {"event": "Tax Audit Report (Form 3CD)", "date": "2026-09-30", "criticality": "High"},
        {"event": "Income Tax Return (ITR)", "date": "2026-10-31", "criticality": "High"}
    ]

    data = {"clients": [], "documents": [], "deadlines": []}
    all_doc_names = [d["name"] for d in document_templates]
    
    for i in range(101, 151):
        client_id = str(i)
        contact = f"{random.choice(first_names)} {random.choice(last_names)}"
        company_name = f"{random.choice(company_prefixes)} {random.choice(company_suffixes)}"
        entity = random.choice(entity_types)
        turnover = f"₹{random.randint(50, 900) / 10} Cr" if entity != "Proprietorship" else f"₹{random.randint(10, 95)} Lakhs"
        
        assigned_docs = random.sample(document_templates, random.randint(3, 5))
        required_doc_names = [d["name"] for d in assigned_docs]

        data["clients"].append({
            "id": client_id,
            "name": company_name,
            "contact_person": contact,
            "email": f"{contact.split()[0].lower()}@{company_name.split()[0].lower()}.in",
            "phone": f"+91 9{random.randint(100000000, 999999999)}",
            "entity_type": entity,
            "annual_turnover": turnover,
            "required_documents": required_doc_names
        })
        
        for doc in assigned_docs:
            status = "missing" if random.random() < 0.3 else "uploaded"
            data["documents"].append({
                "client_id": client_id,
                "doc_name": doc["name"],
                "status": status,
                "due_date": doc["due"]
            })
            
        for d in random.sample(deadline_templates, random.randint(1, 2)):
            data["deadlines"].append({
                "client_id": client_id,
                "event": d["event"],
                "date": d["date"],
                "criticality": d["criticality"]
            })

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

if __name__ == "__main__":
    generate_mock_data()