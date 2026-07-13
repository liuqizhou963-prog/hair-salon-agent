"""Create repeatable customer, wallet, appointment, and package demo data."""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta

from backend.database.connection import SessionLocal, init_db
from backend.database.models import (
    Appointment,
    AppointmentStatus,
    CustomerPackage,
    CustomerPackageStatus,
    Member,
    MemberLevel,
    Notification,
    PointTransaction,
    ReminderLog,
    ServicePackage,
    ServiceVerification,
    ServiceVerificationStatus,
    Stylist,
    StylistTimeSlot,
    Transaction,
    User,
    UserRole,
    WalletAccount,
    WalletDirection,
    WalletTransaction,
    WalletTransactionType,
)
from backend.database.retention import RetentionService


CUSTOMER_COUNT = 150
DEMO_PHONE_PREFIX = "1337000"
PACKAGE_CUSTOMER_COUNT = 8

PACKAGE_DEFINITIONS = [
    {"name": "欧莱雅烫染护理", "service": "烫染护理", "price": 298.0, "uses": 1, "validity_days": 365},
    {"name": "深层修护护理套餐", "service": "深层护理", "price": 688.0, "uses": 3, "validity_days": 365},
    {"name": "头皮舒缓护理套餐", "service": "头皮护理", "price": 598.0, "uses": 3, "validity_days": 180},
    {"name": "轻盈造型体验套餐", "service": "造型", "price": 399.0, "uses": 2, "validity_days": 180},
]

NORMAL_SERVICES = [
    ("剪发", 98.0),
    ("染发", 398.0),
    ("烫发", 598.0),
    ("深层护理", 198.0),
    ("头皮护理", 268.0),
]

CUSTOMER_NAMES = [
    "龙百川", "陈雨桐", "周子轩", "林晓雅", "许安然", "沈佳怡", "顾明远", "苏婉宁",
    "唐浩然", "叶知秋", "宋嘉宁", "程思远", "韩露", "方泽宇", "何欣怡", "陆景行",
    "蒋依依", "魏子昂", "罗诗涵", "邱晨曦", "丁若琳", "邹凯", "袁梦瑶", "傅言",
    "夏清欢", "白芷", "谢雨泽", "孟欣然", "江亦辰", "郝美玲",
]


def _phone(index: int) -> str:
    return f"{DEMO_PHONE_PREFIX}{index + 3:04d}"


def _name(index: int) -> str:
    if index < len(CUSTOMER_NAMES):
        return CUSTOMER_NAMES[index]
    return f"演示客户{index + 1:03d}"


def _bounded_normal(rng: random.Random, mean: float, deviation: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, rng.gauss(mean, deviation)))


def _service_cycle(service: str) -> int:
    if "剪" in service:
        return 28
    if "染" in service:
        return 49
    if "烫" in service:
        return 56
    if "头皮" in service or "护理" in service:
        return 30
    return 35


def _visit_plan(index: int, today: datetime, rng: random.Random) -> tuple[list[datetime], list[str]]:
    if index == 0:
        return [datetime(2026, 5, 19, 15, 0)], ["烫染护理"]

    if index < 16:
        last_days = round(_bounded_normal(rng, 225, 32, 175, 300))
    elif index < 31:
        last_days = round(_bounded_normal(rng, 18, 8, 3, 35))
    else:
        last_days = round(_bounded_normal(rng, 78, 38, 3, 160))

    visit_count = round(_bounded_normal(rng, 3.0, 1.05, 1, 6))
    last_visit = today - timedelta(days=last_days)
    latest_to_oldest = [last_visit]
    latest_services = [rng.choice(NORMAL_SERVICES)[0]]
    for _ in range(1, visit_count):
        previous_service = latest_services[-1]
        gap = round(_bounded_normal(rng, _service_cycle(previous_service), 10, 18, 75))
        latest_to_oldest.append(latest_to_oldest[-1] - timedelta(days=gap))
        latest_services.append(rng.choice(NORMAL_SERVICES)[0])

    oldest = latest_to_oldest[-1]
    if (today - oldest).days > 360:
        shift = (today - oldest).days - 360
        latest_to_oldest = [item + timedelta(days=shift) for item in latest_to_oldest]

    return list(reversed(latest_to_oldest)), list(reversed(latest_services))


def _service_package(db, definition: dict) -> ServicePackage:
    package = db.query(ServicePackage).filter(ServicePackage.name == definition["name"]).first()
    if package:
        return package
    package = ServicePackage(
        id=uuid.uuid4(),
        name=definition["name"],
        service=definition["service"],
        price=definition["price"],
        total_uses=definition["uses"],
        validity_days=definition["validity_days"],
        is_active=True,
    )
    db.add(package)
    db.flush()
    return package


def _reset_demo_customers(db) -> int:
    customers = db.query(User).filter(User.phone.like(f"{DEMO_PHONE_PREFIX}%")).all()
    if not customers:
        return 0

    customer_ids = [customer.id for customer in customers]
    appointments = db.query(Appointment).filter(Appointment.customer_id.in_(customer_ids)).all()
    appointment_ids = [appointment.id for appointment in appointments]
    slot_ids = [appointment.time_slot_id for appointment in appointments]

    db.query(ReminderLog).filter(ReminderLog.customer_id.in_(customer_ids)).delete(synchronize_session=False)
    db.query(ServiceVerification).filter(ServiceVerification.customer_id.in_(customer_ids)).delete(synchronize_session=False)
    db.query(CustomerPackage).filter(CustomerPackage.customer_id.in_(customer_ids)).delete(synchronize_session=False)
    db.query(Transaction).filter(Transaction.user_id.in_(customer_ids)).delete(synchronize_session=False)
    db.query(WalletTransaction).filter(WalletTransaction.user_id.in_(customer_ids)).delete(synchronize_session=False)
    db.query(PointTransaction).filter(PointTransaction.user_id.in_(customer_ids)).delete(synchronize_session=False)
    db.query(Notification).filter(Notification.user_id.in_(customer_ids)).delete(synchronize_session=False)
    db.query(WalletAccount).filter(WalletAccount.user_id.in_(customer_ids)).delete(synchronize_session=False)
    db.query(Member).filter(Member.user_id.in_(customer_ids)).delete(synchronize_session=False)
    if slot_ids:
        db.query(StylistTimeSlot).filter(StylistTimeSlot.id.in_(slot_ids)).update(
            {StylistTimeSlot.booked_by_appointment_id: None}, synchronize_session=False
        )
    if appointment_ids:
        db.query(Appointment).filter(Appointment.id.in_(appointment_ids)).delete(synchronize_session=False)
        db.query(StylistTimeSlot).filter(StylistTimeSlot.id.in_(slot_ids)).delete(synchronize_session=False)
    db.query(User).filter(User.id.in_(customer_ids)).delete(synchronize_session=False)
    db.flush()
    return len(customers)


def _wallet_transaction(
    db,
    user: User,
    wallet: WalletAccount,
    amount_cents: int,
    direction: WalletDirection,
    transaction_type: WalletTransactionType,
    created_at: datetime,
    note: str,
    reference_type: str | None = None,
    reference_id: str | None = None,
) -> WalletTransaction:
    if direction == WalletDirection.CREDIT:
        wallet.balance_cents += amount_cents
    else:
        if wallet.balance_cents < amount_cents:
            raise ValueError(f"演示客户余额不足: {user.phone}")
        wallet.balance_cents -= amount_cents
    transaction = WalletTransaction(
        id=uuid.uuid4(),
        wallet_id=wallet.id,
        user_id=user.id,
        amount_cents=amount_cents,
        direction=direction,
        transaction_type=transaction_type,
        balance_after_cents=wallet.balance_cents,
        reference_type=reference_type,
        reference_id=reference_id,
        note=note,
        created_at=created_at,
    )
    db.add(transaction)
    return transaction


def _create_appointment(db, customer: User, stylist: Stylist, when: datetime, service: str) -> Appointment:
    slot = StylistTimeSlot(
        id=uuid.uuid4(),
        stylist_id=stylist.id,
        date=when.strftime("%Y-%m-%d"),
        time=when.strftime("%H:%M"),
        is_booked=True,
        created_at=when,
    )
    db.add(slot)
    db.flush()
    appointment = Appointment(
        id=uuid.uuid4(),
        customer_id=customer.id,
        stylist_id=stylist.id,
        time_slot_id=slot.id,
        service=service,
        notes="演示历史消费数据",
        status=AppointmentStatus.COMPLETED,
        appointment_datetime=when,
        created_at=when - timedelta(days=2),
        updated_at=when,
    )
    db.add(appointment)
    db.flush()
    slot.booked_by_appointment_id = appointment.id
    return appointment


def _ensure_demo_slots(db, stylists: list[Stylist], today: datetime) -> None:
    for stylist in stylists:
        for day_offset in range(7):
            date = today.date() + timedelta(days=day_offset)
            if date.weekday() >= 5:
                continue
            for hour in range(9, 18):
                date_value = date.strftime("%Y-%m-%d")
                time_value = f"{hour:02d}:00"
                existing = db.query(StylistTimeSlot).filter(
                    StylistTimeSlot.stylist_id == stylist.id,
                    StylistTimeSlot.date == date_value,
                    StylistTimeSlot.time == time_value,
                ).first()
                if not existing:
                    db.add(StylistTimeSlot(
                        id=uuid.uuid4(),
                        stylist_id=stylist.id,
                        date=date_value,
                        time=time_value,
                        is_booked=False,
                        created_at=today,
                    ))
    db.flush()


def _create_upcoming_demo_appointments(db, stylists: list[Stylist], today: datetime) -> int:
    _ensure_demo_slots(db, stylists, today)
    customers = db.query(User).filter(
        User.phone.like(f"{DEMO_PHONE_PREFIX}%"),
        User.role == UserRole.CUSTOMER,
    ).order_by(User.phone).all()
    services = ["剪发", "染发", "深层护理"]
    created = 0
    today_value = today.strftime("%Y-%m-%d")

    for stylist_index, stylist in enumerate(stylists):
        slots = db.query(StylistTimeSlot).filter(
            StylistTimeSlot.stylist_id == stylist.id,
            StylistTimeSlot.is_booked.is_(False),
            StylistTimeSlot.date >= today_value,
            StylistTimeSlot.date < (today.date() + timedelta(days=7)).strftime("%Y-%m-%d"),
        ).order_by(StylistTimeSlot.date, StylistTimeSlot.time).all()
        for slot_index, slot in enumerate(slots[:3]):
            customer = customers[1 + stylist_index * 3 + slot_index]
            appointment_datetime = datetime.strptime(
                f"{slot.date} {slot.time}", "%Y-%m-%d %H:%M"
            )
            appointment = Appointment(
                id=uuid.uuid4(),
                customer_id=customer.id,
                stylist_id=stylist.id,
                time_slot_id=slot.id,
                service=services[(stylist_index + slot_index) % len(services)],
                notes="演示近期预约",
                status=AppointmentStatus.CONFIRMED,
                appointment_datetime=appointment_datetime,
                created_at=today - timedelta(days=2),
                updated_at=today,
            )
            db.add(appointment)
            db.flush()
            slot.is_booked = True
            slot.booked_by_appointment_id = appointment.id
            created += 1
    return created


def _service_amount(service: str, rng: random.Random) -> float:
    if service == "烫染护理":
        return 298.0
    base = next(amount for name, amount in NORMAL_SERVICES if name == service)
    return round(max(68.0, _bounded_normal(rng, base, max(8.0, base * 0.08), base * 0.85, base * 1.2)), 2)


def _seed_customer(db, index: int, stylists: list[Stylist], packages: list[ServicePackage], today: datetime, rng: random.Random) -> None:
    visits, services = _visit_plan(index, today, rng)
    package = packages[index % len(packages)] if index < PACKAGE_CUSTOMER_COUNT else None
    assigned_stylist = stylists[index % len(stylists)] if package else None
    normal_amounts = [_service_amount(service, rng) for service in services]
    if package:
        normal_amounts[0] = package.price
        expected_spend = package.price + sum(normal_amounts[1:])
    else:
        expected_spend = sum(normal_amounts)

    if index == 0:
        recharge_amount = 1000.0
    else:
        target_balance = _bounded_normal(rng, 180, 150, 0, 620) if rng.random() < 0.62 else 0
        if target_balance < 30:
            target_balance = 0
        recharge_amount = round(expected_spend + target_balance, 2)

    customer = User(
        id=uuid.uuid4(),
        name=_name(index),
        phone=_phone(index),
        role=UserRole.CUSTOMER,
        birthday=(today + timedelta(days=index % 12)).strftime("%m-%d") if index % 15 == 0 else f"{(index % 12) + 1:02d}-{(index * 7 % 28) + 1:02d}",
        created_at=min(visits) - timedelta(days=20),
        last_visit=max(visits),
        total_spent=expected_spend,
        is_active=True,
    )
    db.add(customer)
    db.flush()

    wallet = WalletAccount(
        id=uuid.uuid4(),
        user_id=customer.id,
        balance_cents=0,
        created_at=min(visits) - timedelta(days=10),
    )
    db.add(wallet)
    db.flush()
    _wallet_transaction(
        db,
        customer,
        wallet,
        round(recharge_amount * 100),
        WalletDirection.CREDIT,
        WalletTransactionType.RECHARGE,
        min(visits) - timedelta(days=10),
        "演示充值",
    )

    member = Member(
        id=uuid.uuid4(),
        user_id=customer.id,
        level=[MemberLevel.SILVER, MemberLevel.GOLD, MemberLevel.PLATINUM][index % 3],
        points=round(expected_spend),
        joined_date=min(visits) - timedelta(days=10),
        expires_at=today + timedelta(days=30 + (index % 12) * 30),
    )
    db.add(member)
    db.flush()

    customer_package = None
    if package:
        purchase_date = min(visits) - timedelta(days=7)
        customer_package = CustomerPackage(
            id=uuid.uuid4(),
            customer_id=customer.id,
            package_id=package.id,
            purchase_price=package.price,
            total_uses=package.total_uses,
            remaining_uses=package.total_uses - 1,
            status=CustomerPackageStatus.EXHAUSTED if package.total_uses == 1 else CustomerPackageStatus.ACTIVE,
            purchased_at=purchase_date,
            expires_at=purchase_date + timedelta(days=package.validity_days),
            created_at=purchase_date,
        )
        db.add(customer_package)
        db.flush()
        _wallet_transaction(
            db,
            customer,
            wallet,
            round(package.price * 100),
            WalletDirection.DEBIT,
            WalletTransactionType.PURCHASE,
            purchase_date,
            f"购买套餐：{package.name}",
            "customer_package",
            str(customer_package.id),
        )

    for visit_index, (when, service, amount) in enumerate(zip(visits, services, normal_amounts)):
        stylist = assigned_stylist if package and visit_index == 0 else stylists[(index + visit_index) % len(stylists)]
        appointment = _create_appointment(db, customer, stylist, when, service)
        db.add(Transaction(
            id=uuid.uuid4(),
            user_id=customer.id,
            appointment_id=appointment.id,
            amount=amount,
            service=service,
            created_at=when,
        ))
        if not package or visit_index != 0:
            _wallet_transaction(
                db,
                customer,
                wallet,
                round(amount * 100),
                WalletDirection.DEBIT,
                WalletTransactionType.PURCHASE,
                when,
                f"消费：{service}",
                "appointment",
                str(appointment.id),
            )
        if package and visit_index == 0:
            db.add(ServiceVerification(
                id=uuid.uuid4(),
                appointment_id=appointment.id,
                customer_id=customer.id,
                stylist_id=stylist.id,
                customer_package_id=customer_package.id,
                service=service,
                amount=amount,
                status=ServiceVerificationStatus.COMPLETED,
                verified_by=stylist.user_id,
                verified_at=when,
                completed_at=when,
                created_at=when,
            ))


def seed_demo_customers() -> dict[str, int]:
    """Rebuild only the generated customer segment and scan retention rules."""
    init_db()
    db = SessionLocal()
    try:
        stylists = (
            db.query(Stylist)
            .join(User)
            .filter(User.role == UserRole.STYLIST)
            .order_by(User.phone)
            .all()
        )
        if len(stylists) < 4:
            raise RuntimeError("至少需要四位发型师后才能生成演示数据")
        reset_count = _reset_demo_customers(db)
        packages = [_service_package(db, definition) for definition in PACKAGE_DEFINITIONS]
        today = datetime.now().replace(microsecond=0)
        rng = random.Random(20260714)
        for index in range(CUSTOMER_COUNT):
            _seed_customer(db, index, stylists[:4], packages, today, rng)
        upcoming_appointments = _create_upcoming_demo_appointments(db, stylists[:4], today)
        db.commit()
        retention_result = RetentionService.scan_and_generate(db)
        return {
            "reset_customers": reset_count,
            "inserted_customers": CUSTOMER_COUNT,
            "package_verifications_added": PACKAGE_CUSTOMER_COUNT,
            "upcoming_appointments_added": upcoming_appointments,
            "retention_reminders_created": retention_result["total"],
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    print(seed_demo_customers())
