from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_engine
from ..models.user import User as UserModel
from ..dependencies.auth import is_active_user, get_current_user, User as PydanticUser
from ..auth import get_db

router = APIRouter()

MONTHLY_PRICE_KES = 83800
YEARLY_PRICE_KES = int(MONTHLY_PRICE_KES * 12 * 0.8)  # 20% discount for yearly

@router.post("/subscribe")
async def subscribe(
    subscription_type: str,
    db: Session = Depends(get_db),
    current_user: PydanticUser = Depends(is_active_user),
):
    user = db.query(UserModel).filter(UserModel.email == current_user.email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if subscription_type not in {"monthly", "yearly"}:
        raise HTTPException(status_code=400, detail="Invalid subscription type")
    now = datetime.now(timezone.utc)
    if subscription_type == "monthly":
        month = now.month + 1
        year = now.year
        if month > 12:
            month = 1
            year += 1
        end = now.replace(year=year, month=month)
        price = MONTHLY_PRICE_KES
    else:
        end = now.replace(year=now.year + 1)
        price = YEARLY_PRICE_KES
    user.subscription_type = subscription_type
    user.subscription_price = price
    user.subscription_start = now
    user.subscription_end = end
    db.add(user)
    db.commit()
    db.refresh(user)
    return {
        "detail": "Subscription updated",
        "type": subscription_type,
        "price": price,
        "valid_until": user.subscription_end.isoformat(),
    }
