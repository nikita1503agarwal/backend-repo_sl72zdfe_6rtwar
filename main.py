import os
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
from typing import List, Optional
from bson.objectid import ObjectId
from datetime import datetime
from database import db, create_document, get_documents
from schemas import User as UserSchema, Menuitem as MenuItemSchema, Order as OrderSchema, OrderItem as OrderItemSchema
import hashlib
import base64

app = FastAPI(title="Li-Fi Smart Canteen API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBasic()

# Utilities

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def obj_id_str(doc):
    if doc is None:
        return doc
    doc["id"] = str(doc.get("_id"))
    if "_id" in doc:
        del doc["_id"]
    return doc


# Auth models
class SignupRequest(BaseModel):
    name: str
    email: str
    password: str
    is_admin: bool = False

class LoginRequest(BaseModel):
    email: str
    password: str

class LoginResponse(BaseModel):
    token: str
    user: dict


@app.get("/")
def root():
    return {"message": "Li-Fi Smart Canteen API running"}


# Basic token storage (DB-based tokens could be added; for simplicity generate stateless token)

def make_token(email: str) -> str:
    raw = f"{email}:{datetime.utcnow().timestamp()}"
    return base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest()).decode()


@app.post("/api/auth/signup")
def signup(payload: SignupRequest):
    existing = db["user"].find_one({"email": payload.email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user = UserSchema(
        name=payload.name,
        email=payload.email,
        password_hash=hash_password(payload.password),
        is_admin=payload.is_admin,
    )
    uid = create_document("user", user)
    created = db["user"].find_one({"_id": ObjectId(uid)})
    return obj_id_str(created)


@app.post("/api/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest):
    user = db["user"].find_one({"email": payload.email})
    if not user or user.get("password_hash") != hash_password(payload.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = make_token(user["email"])
    return LoginResponse(token=token, user=obj_id_str(user))


# Menu CRUD
class MenuCreate(BaseModel):
    title: str
    description: Optional[str] = None
    price: float
    image_url: Optional[str] = None
    available: bool = True


@app.get("/api/menu")
def list_menu():
    items = list(db["menuitem"].find())
    return [obj_id_str(i) for i in items]


@app.post("/api/menu")
def create_menu_item(payload: MenuCreate):
    item = MenuItemSchema(**payload.model_dump())
    mid = create_document("menuitem", item)
    created = db["menuitem"].find_one({"_id": ObjectId(mid)})
    return obj_id_str(created)


@app.put("/api/menu/{item_id}")
def update_menu_item(item_id: str, payload: MenuCreate):
    res = db["menuitem"].update_one({"_id": ObjectId(item_id)}, {"$set": payload.model_dump() | {"updated_at": datetime.utcnow()}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Item not found")
    updated = db["menuitem"].find_one({"_id": ObjectId(item_id)})
    return obj_id_str(updated)


@app.delete("/api/menu/{item_id}")
def delete_menu_item(item_id: str):
    res = db["menuitem"].delete_one({"_id": ObjectId(item_id)})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"success": True}


# Orders
class CreateOrderRequest(BaseModel):
    user_id: str
    items: List[OrderItemSchema]
    payment_method: str


@app.post("/api/orders")
def create_order(payload: CreateOrderRequest):
    # compute totals
    total = sum([it.qty * it.price for it in payload.items])
    eta = max(10, 5 * len(payload.items))
    # generate QR content
    qr_content = f"ORDER|{payload.user_id}|{datetime.utcnow().isoformat()}|{total}"
    order = OrderSchema(
        user_id=payload.user_id,
        items=[OrderItemSchema(**i.model_dump()) for i in payload.items],
        total=total,
        payment_method=payload.payment_method,
        status="Pending",
        eta_minutes=eta,
        qr_code=qr_content,
    )
    oid = create_document("order", order)
    created = db["order"].find_one({"_id": ObjectId(oid)})
    return obj_id_str(created)


@app.get("/api/orders")
def list_orders(status: Optional[str] = None):
    query = {"status": status} if status else {}
    items = list(db["order"].find(query).sort("created_at", -1))
    return [obj_id_str(i) for i in items]


class UpdateOrderStatus(BaseModel):
    status: str


@app.put("/api/orders/{order_id}/status")
def update_order_status(order_id: str, payload: UpdateOrderStatus):
    if payload.status not in ["Pending", "Preparing", "Ready", "Completed"]:
        raise HTTPException(status_code=400, detail="Invalid status")
    res = db["order"].update_one({"_id": ObjectId(order_id)}, {"$set": {"status": payload.status, "updated_at": datetime.utcnow()}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Order not found")
    updated = db["order"].find_one({"_id": ObjectId(order_id)})
    return obj_id_str(updated)


@app.get("/api/orders/user/{user_id}")
def orders_by_user(user_id: str):
    items = list(db["order"].find({"user_id": user_id}).sort("created_at", -1))
    return [obj_id_str(i) for i in items]


# Analytics
@app.get("/api/analytics/daily")
def analytics_daily():
    today = datetime.utcnow().date()
    start = datetime(today.year, today.month, today.day)
    pipeline = [
        {"$match": {"created_at": {"$gte": start}}},
        {"$group": {"_id": None, "total_sales": {"$sum": "$total"}, "orders": {"$sum": 1}}},
    ]
    result = list(db["order"].aggregate(pipeline))
    data = result[0] if result else {"total_sales": 0, "orders": 0}
    # most ordered items
    pipeline_items = [
        {"$unwind": "$items"},
        {"$group": {"_id": "$items.title", "count": {"$sum": "$items.qty"}}},
        {"$sort": {"count": -1}},
        {"$limit": 5},
    ]
    top_items = list(db["order"].aggregate(pipeline_items))
    return {"total_sales": data.get("total_sales", 0), "orders": data.get("orders", 0), "top_items": top_items}


# Simulated Li-Fi endpoint
class LiFiPayload(BaseModel):
    order_id: str
    payload: dict


@app.post("/api/lifi/send")
def lifi_send(data: LiFiPayload):
    # In a real Li-Fi, this would transfer via light; here we simulate with a state change and echo back
    order = db["order"].find_one({"_id": ObjectId(data.order_id)})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    # mark as preparing as a side-effect to simulate acknowledgement
    db["order"].update_one({"_id": ObjectId(data.order_id)}, {"$set": {"status": "Preparing", "updated_at": datetime.utcnow()}})
    return {"status": "ACK", "received": True, "order_id": data.order_id, "effect": "Order moved to Preparing"}


# Schema inspector for the built-in DB viewer
@app.get("/schema")
def get_schema_defs():
    from inspect import getmembers, isclass
    import schemas as s
    models = {name: cls.model_json_schema() for name, cls in getmembers(s) if isclass(cls) and hasattr(cls, 'model_json_schema')}
    return models


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
