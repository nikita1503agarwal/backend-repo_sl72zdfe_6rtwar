"""
Database Schemas for Li-Fi Based Smart Canteen Ordering System

Each Pydantic model represents a collection in MongoDB.
Collection name is the lowercase class name.
"""

from pydantic import BaseModel, Field
from typing import Optional, List

class User(BaseModel):
    name: str = Field(..., description="Full name")
    email: str = Field(..., description="Email address")
    password_hash: str = Field(..., description="Hashed password")
    is_admin: bool = Field(False, description="Admin user flag")

class Menuitem(BaseModel):
    title: str = Field(..., description="Item name")
    description: Optional[str] = Field(None, description="Item description")
    price: float = Field(..., ge=0, description="Price in currency units")
    image_url: Optional[str] = Field(None, description="Image URL")
    available: bool = Field(True, description="Availability status")

class OrderItem(BaseModel):
    item_id: str = Field(..., description="Menu item id (string)")
    title: str = Field(..., description="Item title snapshot")
    qty: int = Field(..., ge=1, description="Quantity")
    price: float = Field(..., ge=0, description="Unit price snapshot")

class Order(BaseModel):
    user_id: str = Field(..., description="User id")
    items: List[OrderItem] = Field(default_factory=list)
    total: float = Field(..., ge=0, description="Total bill amount")
    payment_method: str = Field(..., description="cash | upi | card")
    status: str = Field("Pending", description="Pending | Preparing | Ready | Completed")
    eta_minutes: int = Field(10, ge=0, description="Estimated preparation time")
    qr_code: Optional[str] = Field(None, description="QR code string payload")
