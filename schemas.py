"""
Database Schemas for InvoiceFlow AI

Each Pydantic model represents a collection in MongoDB. The collection name is the lowercase
of the class name (e.g., User -> "user", Invoice -> "invoice").
"""

from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import date

class User(BaseModel):
    """
    Users collection schema
    Collection name: "user"
    """
    name: str = Field(..., description="Full name")
    email: str = Field(..., description="Email address")
    subscription_tier: Literal["Free", "Pro"] = Field("Free", description="Subscription tier")
    credits_remaining: int = Field(50, ge=0, description="Remaining credits for AI extraction")
    role: Literal["admin", "customer"] = Field("customer", description="User role for access control")

class Invoice(BaseModel):
    """
    Invoices collection schema
    Collection name: "invoice"
    """
    user_id: str = Field(..., description="ID of the user who uploaded the invoice")
    file_path: Optional[str] = Field(None, description="Local path to stored file")
    file_name: Optional[str] = Field(None, description="Original filename")
    invoice_number: Optional[str] = Field(None, description="Invoice number")
    vendor_name: Optional[str] = Field(None, description="Vendor name")
    date: Optional[date] = Field(None, description="Invoice date")
    total_amount: Optional[float] = Field(None, ge=0, description="Total amount")
    status: Literal["Processing", "Needs Review", "Approved"] = Field("Processing", description="Review status")
