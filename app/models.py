from datetime import datetime, date
from decimal import Decimal
from typing import List, Optional, Any

from sqlalchemy import (
    String, Integer, BigInteger, Boolean, Text, Numeric,
    DateTime, Date, ForeignKey
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import JSONB


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    bsale_user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    bsale_office_id: Mapped[Optional[int]] = mapped_column(ForeignKey("offices.bsale_office_id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", default=True, nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    office: Mapped[Optional["Office"]] = relationship("Office", back_populates="users")
    documents: Mapped[List["Document"]] = relationship("Document", back_populates="user")
    receptions: Mapped[List["Reception"]] = relationship("Reception", back_populates="user")


class Department(Base):
    __tablename__ = "departments"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(180), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    categories: Mapped[List["Category"]] = relationship("Category", back_populates="department", cascade="all, delete-orphan")


class Category(Base):
    __tablename__ = "categories"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(230), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    department: Mapped["Department"] = relationship("Department", back_populates="categories")
    subcategories: Mapped[List["Subcategory"]] = relationship("Subcategory", back_populates="category", cascade="all, delete-orphan")


class Subcategory(Base):
    __tablename__ = "subcategories"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(230), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    category: Mapped["Category"] = relationship("Category", back_populates="subcategories")
    product_types: Mapped[List["ProductType"]] = relationship("ProductType", back_populates="subcategory")
    products: Mapped[List["Product"]] = relationship("Product", back_populates="subcategory")


class ProductType(Base):
    __tablename__ = "product_types"
    
    bsale_product_type_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    subcategory_id: Mapped[Optional[int]] = mapped_column(ForeignKey("subcategories.id", ondelete="SET NULL"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", default=True, nullable=False)
    is_mapped: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False, nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    subcategory: Mapped[Optional["Subcategory"]] = relationship("Subcategory", back_populates="product_types")
    products: Mapped[List["Product"]] = relationship("Product", back_populates="product_type")
    attributes: Mapped[List["ProductTypeAttribute"]] = relationship("ProductTypeAttribute", back_populates="product_type", cascade="all, delete-orphan")


class ProductTypeAttribute(Base):
    __tablename__ = "product_type_attributes"
    
    bsale_attribute_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bsale_product_type_id: Mapped[Optional[int]] = mapped_column(ForeignKey("product_types.bsale_product_type_id", ondelete="CASCADE"), nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    product_type: Mapped[Optional["ProductType"]] = relationship("ProductType", back_populates="attributes")
    variant_attribute_values: Mapped[List["VariantAttributeValue"]] = relationship("VariantAttributeValue", back_populates="attribute", cascade="all, delete-orphan")


class Product(Base):
    __tablename__ = "products"
    
    bsale_product_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    bsale_product_type_id: Mapped[Optional[int]] = mapped_column(ForeignKey("product_types.bsale_product_type_id", ondelete="SET NULL"), nullable=True)
    subcategory_id: Mapped[Optional[int]] = mapped_column(ForeignKey("subcategories.id", ondelete="SET NULL"), nullable=True)
    stock_control: Mapped[bool] = mapped_column(Boolean, server_default="true", default=True, nullable=False)
    allow_decimal: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", default=True, nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    product_type: Mapped[Optional["ProductType"]] = relationship("ProductType", back_populates="products")
    subcategory: Mapped[Optional["Subcategory"]] = relationship("Subcategory", back_populates="products")
    variants: Mapped[List["Variant"]] = relationship("Variant", back_populates="product")


class Variant(Base):
    __tablename__ = "variants"
    
    bsale_variant_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bsale_product_id: Mapped[Optional[int]] = mapped_column(ForeignKey("products.bsale_product_id", ondelete="SET NULL"), nullable=True)
    code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    bar_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    display_code: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    allow_negative_stock: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", default=True, nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    product: Mapped[Optional["Product"]] = relationship("Product", back_populates="variants")
    attribute_values: Mapped[List["VariantAttributeValue"]] = relationship("VariantAttributeValue", back_populates="variant")
    costs: Mapped[Optional["VariantCost"]] = relationship("VariantCost", back_populates="variant", uselist=False)
    stock_levels: Mapped[List["StockLevel"]] = relationship("StockLevel", back_populates="variant")
    stock_history: Mapped[List["StockHistory"]] = relationship("StockHistory", back_populates="variant")
    document_details: Mapped[List["DocumentDetail"]] = relationship("DocumentDetail", back_populates="variant")
    reception_details: Mapped[List["ReceptionDetail"]] = relationship("ReceptionDetail", back_populates="variant")
    consumption_details: Mapped[List["ConsumptionDetail"]] = relationship("ConsumptionDetail", back_populates="variant")


class VariantAttributeValue(Base):
    __tablename__ = "variant_attribute_values"
    
    bsale_av_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bsale_variant_id: Mapped[int] = mapped_column(ForeignKey("variants.bsale_variant_id", ondelete="CASCADE"), nullable=False)
    bsale_attribute_id: Mapped[int] = mapped_column(ForeignKey("product_type_attributes.bsale_attribute_id", ondelete="CASCADE"), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    variant: Mapped["Variant"] = relationship("Variant", back_populates="attribute_values")
    attribute: Mapped["ProductTypeAttribute"] = relationship("ProductTypeAttribute", back_populates="variant_attribute_values")


class VariantCost(Base):
    __tablename__ = "variant_costs"
    
    bsale_variant_id: Mapped[int] = mapped_column(ForeignKey("variants.bsale_variant_id", ondelete="CASCADE"), primary_key=True)
    average_cost: Mapped[Decimal] = mapped_column(Numeric(20, 4), server_default="0", default=Decimal('0.0'), nullable=False)
    latest_cost: Mapped[Decimal] = mapped_column(Numeric(20, 4), server_default="0", default=Decimal('0.0'), nullable=False)
    cost_source: Mapped[str] = mapped_column(String(20), server_default="NONE", default="NONE", nullable=False)
    effective_cost: Mapped[Decimal] = mapped_column(Numeric(20, 4), server_default="0", default=Decimal('0.0'), nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    variant: Mapped["Variant"] = relationship("Variant", back_populates="costs")


class Office(Base):
    __tablename__ = "offices"
    
    bsale_office_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    district: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(100), server_default="Peru", default="Peru", nullable=True)
    is_virtual: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", default=True, nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    documents: Mapped[List["Document"]] = relationship("Document", back_populates="office")
    receptions: Mapped[List["Reception"]] = relationship("Reception", back_populates="office")
    consumptions: Mapped[List["Consumption"]] = relationship("Consumption", back_populates="office")
    stock_levels: Mapped[List["StockLevel"]] = relationship("StockLevel", back_populates="office")
    stock_history: Mapped[List["StockHistory"]] = relationship("StockHistory", back_populates="office")
    users: Mapped[List["User"]] = relationship("User", back_populates="office")


class DocumentType(Base):
    __tablename__ = "document_types"
    
    bsale_document_type_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    is_credit_note: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False, nullable=False)
    is_sales_note: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False, nullable=False)
    is_electronic: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", default=True, nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    documents: Mapped[List["Document"]] = relationship("Document", back_populates="document_type")


class Document(Base):
    __tablename__ = "documents"
    
    bsale_document_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bsale_document_type_id: Mapped[int] = mapped_column(ForeignKey("document_types.bsale_document_type_id"), nullable=False)
    bsale_office_id: Mapped[Optional[int]] = mapped_column(ForeignKey("offices.bsale_office_id"), nullable=True)
    emission_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    generation_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    serial_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    doc_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), server_default="0", default=Decimal('0.0'), nullable=False)
    net_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), server_default="0", default=Decimal('0.0'), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), server_default="0", default=Decimal('0.0'), nullable=False)
    exempt_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), server_default="0", default=Decimal('0.0'), nullable=False)
    is_credit_note: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", default=True, nullable=False)
    bsale_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.bsale_user_id"), nullable=True)
    token: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    document_type: Mapped["DocumentType"] = relationship("DocumentType", back_populates="documents")
    office: Mapped[Optional["Office"]] = relationship("Office", back_populates="documents")
    user: Mapped[Optional["User"]] = relationship("User", back_populates="documents")
    details: Mapped[List["DocumentDetail"]] = relationship("DocumentDetail", back_populates="document", cascade="all, delete-orphan")


class DocumentDetail(Base):
    __tablename__ = "document_details"
    
    bsale_detail_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bsale_document_id: Mapped[int] = mapped_column(ForeignKey("documents.bsale_document_id", ondelete="CASCADE"), nullable=False)
    bsale_variant_id: Mapped[int] = mapped_column(ForeignKey("variants.bsale_variant_id", ondelete="CASCADE"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 4), server_default="0", default=Decimal('0.0'), nullable=False)
    net_unit_value: Mapped[Decimal] = mapped_column(Numeric(20, 4), server_default="0", default=Decimal('0.0'), nullable=False)
    net_unit_value_raw: Mapped[Decimal] = mapped_column(Numeric(20, 4), server_default="0", default=Decimal('0.0'), nullable=False)
    total_unit_value: Mapped[Decimal] = mapped_column(Numeric(20, 4), server_default="0", default=Decimal('0.0'), nullable=False)
    net_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), server_default="0", default=Decimal('0.0'), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), server_default="0", default=Decimal('0.0'), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), server_default="0", default=Decimal('0.0'), nullable=False)
    discount_percentage: Mapped[Decimal] = mapped_column(Numeric(6, 2), server_default="0", default=Decimal('0.0'), nullable=False)
    net_discount: Mapped[Decimal] = mapped_column(Numeric(20, 2), server_default="0", default=Decimal('0.0'), nullable=False)
    is_gratuity: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False, nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    document: Mapped["Document"] = relationship("Document", back_populates="details")
    variant: Mapped["Variant"] = relationship("Variant", back_populates="document_details")


class Reception(Base):
    __tablename__ = "receptions"
    
    bsale_reception_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bsale_office_id: Mapped[int] = mapped_column(ForeignKey("offices.bsale_office_id", ondelete="CASCADE"), nullable=False)
    admission_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    admission_date_raw: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    document_ref: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    document_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_internal_dispatch: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False, nullable=False)
    is_transfer: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False, nullable=False)
    bsale_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.bsale_user_id"), nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    office: Mapped["Office"] = relationship("Office", back_populates="receptions")
    user: Mapped[Optional["User"]] = relationship("User", back_populates="receptions")
    details: Mapped[List["ReceptionDetail"]] = relationship("ReceptionDetail", back_populates="reception", cascade="all, delete-orphan")


class ReceptionDetail(Base):
    __tablename__ = "reception_details"
    
    bsale_reception_detail_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bsale_reception_id: Mapped[int] = mapped_column(ForeignKey("receptions.bsale_reception_id", ondelete="CASCADE"), nullable=False)
    bsale_variant_id: Mapped[int] = mapped_column(ForeignKey("variants.bsale_variant_id", ondelete="CASCADE"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 4), server_default="0", default=Decimal('0.0'), nullable=False)
    cost: Mapped[Decimal] = mapped_column(Numeric(20, 4), server_default="0", default=Decimal('0.0'), nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    reception: Mapped["Reception"] = relationship("Reception", back_populates="details")
    variant: Mapped["Variant"] = relationship("Variant", back_populates="reception_details")


class Consumption(Base):
    __tablename__ = "consumptions"

    bsale_consumption_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bsale_office_id: Mapped[int] = mapped_column(ForeignKey("offices.bsale_office_id", ondelete="CASCADE"), nullable=False)
    consumption_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=True)

    office: Mapped["Office"] = relationship("Office", back_populates="consumptions")
    details: Mapped[List["ConsumptionDetail"]] = relationship("ConsumptionDetail", back_populates="consumption", cascade="all, delete-orphan")


class ConsumptionDetail(Base):
    __tablename__ = "consumption_details"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bsale_consumption_id: Mapped[int] = mapped_column(ForeignKey("consumptions.bsale_consumption_id", ondelete="CASCADE"), nullable=False)
    bsale_variant_id: Mapped[int] = mapped_column(ForeignKey("variants.bsale_variant_id", ondelete="CASCADE"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=True)

    consumption: Mapped["Consumption"] = relationship("Consumption", back_populates="details")
    variant: Mapped["Variant"] = relationship("Variant", back_populates="consumption_details")


class StockLevel(Base):
    __tablename__ = "stock_levels"
    
    bsale_stock_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bsale_variant_id: Mapped[int] = mapped_column(ForeignKey("variants.bsale_variant_id", ondelete="CASCADE"), nullable=False)
    bsale_office_id: Mapped[int] = mapped_column(ForeignKey("offices.bsale_office_id", ondelete="CASCADE"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 4), server_default="0", default=Decimal('0.0'), nullable=False)
    quantity_reserved: Mapped[Decimal] = mapped_column(Numeric(20, 4), server_default="0", default=Decimal('0.0'), nullable=False)
    quantity_available: Mapped[Decimal] = mapped_column(Numeric(20, 4), server_default="0", default=Decimal('0.0'), nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    variant: Mapped["Variant"] = relationship("Variant", back_populates="stock_levels")
    office: Mapped["Office"] = relationship("Office", back_populates="stock_levels")


class StockHistory(Base):
    __tablename__ = "stock_history"
    
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    bsale_variant_id: Mapped[int] = mapped_column(ForeignKey("variants.bsale_variant_id", ondelete="CASCADE"), nullable=False)
    bsale_office_id: Mapped[int] = mapped_column(ForeignKey("offices.bsale_office_id", ondelete="CASCADE"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 4), server_default="0", default=Decimal('0.0'), nullable=False)
    quantity_reserved: Mapped[Decimal] = mapped_column(Numeric(20, 4), server_default="0", default=Decimal('0.0'), nullable=False)
    quantity_available: Mapped[Decimal] = mapped_column(Numeric(20, 4), server_default="0", default=Decimal('0.0'), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    variant: Mapped["Variant"] = relationship("Variant", back_populates="stock_history")
    office: Mapped["Office"] = relationship("Office", back_populates="stock_history")


class SyncLog(Base):
    __tablename__ = "sync_log"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(20), server_default="RUNNING", default="RUNNING", nullable=False)
    params: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    records_fetched: Mapped[int] = mapped_column(Integer, server_default="0", default=0, nullable=False)
    records_inserted: Mapped[int] = mapped_column(Integer, server_default="0", default=0, nullable=False)
    records_updated: Mapped[int] = mapped_column(Integer, server_default="0", default=0, nullable=False)
    records_skipped: Mapped[int] = mapped_column(Integer, server_default="0", default=0, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class DataQualityIssue(Base):
    __tablename__ = "data_quality_issues"
    
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    entity: Mapped[str] = mapped_column(String(80), nullable=False)
    bsale_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    field: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    issue_type: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
