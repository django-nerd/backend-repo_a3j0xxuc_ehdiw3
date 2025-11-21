import os
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from database import db, create_document, get_documents
from schemas import User as UserSchema, Invoice as InvoiceSchema

app = FastAPI(title="InvoiceFlow AI API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------- Health ---------
@app.get("/health")
def health():
    return {"ok": True}

# --------- Models for requests/responses ---------
class CreateUserRequest(BaseModel):
    name: str
    email: str
    subscription_tier: str = "Free"
    role: str = "customer"

class UpdateInvoiceRequest(BaseModel):
    invoice_id: str
    invoice_number: Optional[str] = None
    vendor_name: Optional[str] = None
    date: Optional[str] = None
    total_amount: Optional[float] = None
    status: Optional[str] = None

# --------- Utils ---------
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

def mock_ai_extract(file_path: str):
    base = os.path.basename(file_path)
    vendor = "Acme Corp"
    invoice_number = f"INV-{int(datetime.now().timestamp())}"
    total_amount = 199.0
    date_str = datetime.now().strftime("%Y-%m-%d")
    name_without_ext = os.path.splitext(base)[0]
    parts = name_without_ext.replace("-", "_").split("_")
    for p in parts:
        if p.replace(".", "", 1).isdigit():
            try:
                total_amount = float(p)
            except Exception:
                pass
        if len(p) >= 3 and p.isalpha():
            vendor = p.capitalize()
        if len(p) == 10 and p[4] == '-' and p[7] == '-':
            date_str = p
    return {
        "vendor_name": vendor,
        "invoice_number": invoice_number,
        "total_amount": total_amount,
        "date": date_str,
    }

# --------- Basic routes ---------
@app.get("/")
def root():
    return {"name": "InvoiceFlow AI", "status": "ok"}

@app.get("/test")
def test_database():
    resp = {"backend": "running", "database": "not connected", "collections": []}
    try:
        if db is not None:
            resp["database"] = "connected"
            resp["collections"] = db.list_collection_names()
    except Exception as e:
        resp["error"] = str(e)
    return resp

# --------- Auth-lite ---------

def get_current_user_id(x_user_id: Optional[str] = Header(default=None)) -> Optional[str]:
    return x_user_id

# --------- Users ---------
@app.post("/api/users")
def create_user(payload: CreateUserRequest):
    user = UserSchema(
        name=payload.name,
        email=payload.email,
        subscription_tier=payload.subscription_tier,
        credits_remaining=50 if payload.subscription_tier == "Free" else 1000,
        role=payload.role,
    )
    user_id = create_document("user", user)
    return {"id": user_id}

@app.get("/api/admin/overview")
def admin_overview(current_user: Optional[str] = Depends(get_current_user_id)):
    users = get_documents("user") if db else []
    invoices = get_documents("invoice") if db else []
    total_usage = len(invoices)
    return {
        "users": [{"id": str(u.get("_id")), "email": u.get("email"), "tier": u.get("subscription_tier")} for u in users],
        "total_invoices": total_usage,
    }

# --------- Invoices ---------
@app.post("/api/invoices/upload")
async def upload_invoice(
    file: UploadFile = File(...),
    current_user: Optional[str] = Depends(get_current_user_id),
):
    if current_user is None:
        raise HTTPException(status_code=401, detail="Missing x-user-id header")

    # Save file to disk
    file_name = f"{int(datetime.now().timestamp())}_{file.filename}"
    file_path = os.path.join(UPLOAD_DIR, file_name)
    with open(file_path, "wb") as f:
        f.write(await file.read())

    inv = InvoiceSchema(
        user_id=current_user,
        file_path=file_path,
        file_name=file.filename,
        status="Processing",
    )
    invoice_id = create_document("invoice", inv)

    # Update with extracted fields
    extracted = mock_ai_extract(file_path)
    try:
        from bson import ObjectId
        db["invoice"].update_one({"_id": ObjectId(invoice_id)}, {"$set": extracted})
    except Exception:
        pass

    return {"id": invoice_id, **extracted, "status": "Needs Review"}

@app.get("/api/invoices")
def list_invoices(current_user: Optional[str] = Depends(get_current_user_id)):
    if current_user is None:
        raise HTTPException(status_code=401, detail="Missing x-user-id header")
    docs = get_documents("invoice", {"user_id": current_user})
    out = []
    for d in docs:
        date_val = d.get("date")
        if isinstance(date_val, datetime):
            date_val = date_val.date().isoformat()
        out.append({
            "id": str(d.get("_id")),
            "file_name": d.get("file_name"),
            "invoice_number": d.get("invoice_number"),
            "vendor_name": d.get("vendor_name"),
            "date": date_val,
            "total_amount": d.get("total_amount"),
            "status": d.get("status", "Processing"),
        })
    return out

@app.post("/api/invoices/update")
def update_invoice(payload: UpdateInvoiceRequest, current_user: Optional[str] = Depends(get_current_user_id)):
    if current_user is None:
        raise HTTPException(status_code=401, detail="Missing x-user-id header")
    try:
        from bson import ObjectId
        updates = {k: v for k, v in payload.model_dump().items() if k != "invoice_id" and v is not None}
        res = db["invoice"].update_one({"_id": ObjectId(payload.invoice_id), "user_id": current_user}, {"$set": updates})
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Invoice not found")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}

@app.get("/api/invoices/export")
def export_invoices_csv(current_user: Optional[str] = Depends(get_current_user_id)):
    if current_user is None:
        raise HTTPException(status_code=401, detail="Missing x-user-id header")
    import csv
    from io import StringIO

    docs = get_documents("invoice", {"user_id": current_user})
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Invoice Number", "Vendor", "Date", "Total Amount", "Status", "File Name"]) 
    for d in docs:
        writer.writerow([
            d.get("invoice_number", ""),
            d.get("vendor_name", ""),
            d.get("date", ""),
            d.get("total_amount", ""),
            d.get("status", ""),
            d.get("file_name", ""),
        ])

    csv_bytes = output.getvalue().encode()
    filename = f"invoices_{current_user}.csv"
    path = os.path.join(UPLOAD_DIR, filename)
    with open(path, "wb") as f:
        f.write(csv_bytes)

    return FileResponse(path, media_type="text/csv", filename=filename)

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
