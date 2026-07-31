import asyncio
from db.session import AsyncSessionLocal
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from models.order_model import Order, OrderItem
from schemas.order_schema import BaseOrder

async def main():
    async with AsyncSessionLocal() as session:
        query = select(Order).where(Order.id == 'c0acec1a-b00b-438b-8f73-e5165efb422b').options(joinedload(Order.order_item).joinedload(OrderItem.product))
        result = await session.execute(query)
        order = result.unique().scalar_one_or_none()
        if order:
            schema = BaseOrder.model_validate(order)
            print(schema.model_dump_json(indent=2))
        else:
            print("Not found")

if __name__ == "__main__":
    asyncio.run(main())
