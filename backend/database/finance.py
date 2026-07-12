"""Wallet, refund, notification, and audit business services."""

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import json
import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.database.models import (
    AuditLog,
    Notification,
    NotificationKind,
    RefundRequest,
    RefundStatus,
    User,
    WalletAccount,
    WalletDirection,
    WalletTransaction,
    WalletTransactionType,
)


class FinanceError(ValueError):
    pass


def amount_to_cents(amount: float) -> int:
    normalized = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    cents = int(normalized * 100)
    if cents <= 0:
        raise FinanceError("金额必须大于 0")
    return cents


def cents_to_amount(cents: int) -> float:
    return float(Decimal(cents) / Decimal(100))


class FinanceService:
    @staticmethod
    def get_or_create_wallet(db: Session, user: User) -> WalletAccount:
        wallet = db.query(WalletAccount).filter(WalletAccount.user_id == user.id).first()
        if wallet:
            return wallet
        wallet = WalletAccount(id=uuid.uuid4(), user_id=user.id, balance_cents=0)
        db.add(wallet)
        db.flush()
        return wallet

    @staticmethod
    def create_notification(
        db: Session, user_id, kind: NotificationKind, title: str, body: str
    ) -> Notification:
        notification = Notification(
            id=uuid.uuid4(),
            user_id=user_id,
            kind=kind,
            title=title,
            body=body,
        )
        db.add(notification)
        return notification

    @staticmethod
    def create_audit(
        db: Session,
        actor_user_id,
        action: str,
        entity_type: str,
        entity_id: str,
        details: dict | None = None,
    ) -> AuditLog:
        audit = AuditLog(
            id=uuid.uuid4(),
            actor_user_id=actor_user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=json.dumps(details or {}, ensure_ascii=False),
        )
        db.add(audit)
        return audit

    @staticmethod
    def _record_wallet_transaction(
        db: Session,
        wallet: WalletAccount,
        user: User,
        amount_cents: int,
        direction: WalletDirection,
        transaction_type: WalletTransactionType,
        note: str | None = None,
        reference_type: str | None = None,
        reference_id: str | None = None,
    ) -> WalletTransaction:
        transaction = WalletTransaction(
            id=uuid.uuid4(),
            wallet_id=wallet.id,
            user_id=user.id,
            amount_cents=amount_cents,
            direction=direction,
            transaction_type=transaction_type,
            balance_after_cents=wallet.balance_cents,
            note=note,
            reference_type=reference_type,
            reference_id=reference_id,
        )
        db.add(transaction)
        return transaction

    @classmethod
    def recharge(cls, db: Session, user: User, amount: float, note: str | None = None):
        cents = amount_to_cents(amount)
        wallet = cls.get_or_create_wallet(db, user)
        wallet.balance_cents += cents
        transaction = cls._record_wallet_transaction(
            db, wallet, user, cents, WalletDirection.CREDIT, WalletTransactionType.RECHARGE,
            note=note or "演示充值",
        )
        cls.create_notification(
            db, user.id, NotificationKind.WALLET, "充值到账",
            f"已到账 {cents_to_amount(cents):.2f} 元，当前余额 {cents_to_amount(wallet.balance_cents):.2f} 元。",
        )
        cls.create_audit(
            db, user.id, "wallet.recharge", "wallet_account", str(wallet.id),
            {"amount_cents": cents, "balance_cents": wallet.balance_cents},
        )
        db.commit()
        db.refresh(wallet)
        db.refresh(transaction)
        return wallet, transaction

    @classmethod
    def request_refund(cls, db: Session, user: User, amount: float, reason: str | None = None):
        cents = amount_to_cents(amount)
        wallet = cls.get_or_create_wallet(db, user)
        pending_cents = db.query(func.coalesce(func.sum(RefundRequest.amount_cents), 0)).filter(
            RefundRequest.user_id == user.id,
            RefundRequest.status == RefundStatus.PENDING,
        ).scalar()
        if cents + int(pending_cents or 0) > wallet.balance_cents:
            raise FinanceError("可退款余额不足或已有待处理退款申请")

        refund = RefundRequest(
            id=uuid.uuid4(),
            user_id=user.id,
            amount_cents=cents,
            status=RefundStatus.PENDING,
            reason=reason,
        )
        db.add(refund)
        db.flush()
        cls.create_notification(
            db, user.id, NotificationKind.REFUND, "退款申请已提交",
            f"{cents_to_amount(cents):.2f} 元退款申请正在等待门店处理。",
        )
        cls.create_audit(
            db, user.id, "refund.request", "refund_request", str(refund.id),
            {"amount_cents": cents},
        )
        db.commit()
        db.refresh(refund)
        return refund

    @classmethod
    def approve_refund(cls, db: Session, refund_id: str, actor: User):
        try:
            refund_uuid = uuid.UUID(refund_id)
        except ValueError as exc:
            raise FinanceError("退款申请不存在") from exc
        refund = db.query(RefundRequest).filter(RefundRequest.id == refund_uuid).first()
        if not refund:
            raise FinanceError("退款申请不存在")
        if refund.status != RefundStatus.PENDING:
            raise FinanceError("退款申请已处理")

        wallet = cls.get_or_create_wallet(db, refund.user)
        if wallet.balance_cents < refund.amount_cents:
            raise FinanceError("当前余额不足，无法审批退款")

        wallet.balance_cents -= refund.amount_cents
        refund.status = RefundStatus.APPROVED
        refund.processed_by = actor.id
        refund.processed_at = datetime.now()
        transaction = cls._record_wallet_transaction(
            db, wallet, refund.user, refund.amount_cents,
            WalletDirection.DEBIT, WalletTransactionType.REFUND,
            note="退款审批通过", reference_type="refund_request", reference_id=str(refund.id),
        )
        cls.create_notification(
            db, refund.user_id, NotificationKind.REFUND, "退款已通过",
            f"{cents_to_amount(refund.amount_cents):.2f} 元退款已处理，当前余额 {cents_to_amount(wallet.balance_cents):.2f} 元。",
        )
        cls.create_audit(
            db, actor.id, "refund.approve", "refund_request", str(refund.id),
            {"amount_cents": refund.amount_cents, "balance_cents": wallet.balance_cents},
        )
        db.commit()
        db.refresh(refund)
        db.refresh(wallet)
        db.refresh(transaction)
        return refund, wallet, transaction

    @classmethod
    def reject_refund(cls, db: Session, refund_id: str, actor: User):
        try:
            refund_uuid = uuid.UUID(refund_id)
        except ValueError as exc:
            raise FinanceError("退款申请不存在") from exc
        refund = db.query(RefundRequest).filter(RefundRequest.id == refund_uuid).first()
        if not refund:
            raise FinanceError("退款申请不存在")
        if refund.status != RefundStatus.PENDING:
            raise FinanceError("退款申请已处理")
        refund.status = RefundStatus.REJECTED
        refund.processed_by = actor.id
        refund.processed_at = datetime.now()
        cls.create_notification(
            db, refund.user_id, NotificationKind.REFUND, "退款申请未通过",
            "门店未通过本次退款申请，请联系门店了解详情。",
        )
        cls.create_audit(db, actor.id, "refund.reject", "refund_request", str(refund.id))
        db.commit()
        db.refresh(refund)
        return refund

    @staticmethod
    def mark_notification_read(db: Session, notification_id: str, user: User) -> Notification | None:
        try:
            notification_uuid = uuid.UUID(notification_id)
        except ValueError:
            return None
        notification = db.query(Notification).filter(
            Notification.id == notification_uuid,
            Notification.user_id == user.id,
        ).first()
        if not notification:
            return None
        if not notification.is_read:
            notification.is_read = True
            notification.read_at = datetime.now()
            db.commit()
            db.refresh(notification)
        return notification
