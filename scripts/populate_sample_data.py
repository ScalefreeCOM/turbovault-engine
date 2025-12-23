"""
Sample Data Population Script for TurboVault Engine

This script creates a complete Data Vault model for a fictional "Pizza Delivery Empire"
including hubs, links, satellites, source systems, and all necessary mappings.

Theme: 🍕 Pizza Delivery Empire - Track customers, pizzas, drivers, and orders!
"""

import os
import sys
import django

# Setup Django - change to backend directory and setup paths
script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.join(script_dir, '..', 'backend')
os.chdir(backend_dir)
sys.path.insert(0, backend_dir)

os.environ['DJANGO_SETTINGS_MODULE'] = 'turbovault.settings'
django.setup()

from engine.models import (
    Project, Group,
    SourceSystem, SourceTable, SourceColumn,
    Hub, HubColumn, HubSourceMapping,
    Link, LinkColumn, LinkSourceMapping,
    Satellite, SatelliteColumn
)


def create_pizza_delivery_project():
    """Create the Pizza Delivery Empire Data Vault project."""
    
    print("🍕 Creating Pizza Delivery Empire Data Vault...\n")
    
    # ============================================================================
    # 1. PROJECT & GROUPS
    # ============================================================================
    print("📋 Creating project...")
    project = Project.objects.create(
        name="pizza_delivery_empire",
        description="Data Vault for tracking pizza orders, customers, drivers, and deliveries",
        config={
            "stage_schema": "stage",
            "rdv_schema": "rdv",
            "hashdiff_naming_pattern": "hd_{entity}"
        }
    )
    
    # Create logical groups for organization
    print("📁 Creating groups...")
    group_customer = Group.objects.create(
        project=project,
        group_name="customer_domain",
        description="Customer-related entities"
    )
    
    group_product = Group.objects.create(
        project=project,
        group_name="product_domain",
        description="Product catalog entities"
    )
    
    group_operations = Group.objects.create(
        project=project,
        group_name="operations_domain",
        description="Operational entities (orders, deliveries)"
    )
    
    # ============================================================================
    # 2. SOURCE SYSTEMS & METADATA
    # ============================================================================
    print("🗄️  Creating source systems...")
    
    # Source System 1: Online Ordering App
    src_ordering_app = SourceSystem.objects.create(
        project=project,
        name="PizzaOrderApp",
        schema_name="ordering",
        database_name="pizza_online_db"
    )
    
    # Source System 2: Delivery Tracking System
    src_delivery_tracking = SourceSystem.objects.create(
        project=project,
        name="DeliveryTracker",
        schema_name="delivery",
        database_name="logistics_db"
    )
    
    # Source System 3: Customer CRM
    src_crm = SourceSystem.objects.create(
        project=project,
        name="CustomerCRM",
        schema_name="crm",
        database_name="crm_master_db"
    )
    
    print("📊 Creating source tables and columns...")
    
    # === Ordering App Tables ===
    
    # Customers table
    tbl_customers = SourceTable.objects.create(
        project=project,
        source_system=src_ordering_app,
        physical_table_name="customers",
        record_source_value="PIZZA_APP",
        load_date_value="app_load_timestamp"
    )
    
    col_customer_id = SourceColumn.objects.create(
        source_table=tbl_customers,
        source_column_physical_name="customer_id",
        source_column_datatype="INTEGER"
    )
    
    col_email = SourceColumn.objects.create(
        source_table=tbl_customers,
        source_column_physical_name="email",
        source_column_datatype="VARCHAR(255)"
    )
    
    col_customer_name = SourceColumn.objects.create(
        source_table=tbl_customers,
        source_column_physical_name="customer_name",
        source_column_datatype="VARCHAR(200)"
    )
    
    col_phone = SourceColumn.objects.create(
        source_table=tbl_customers,
        source_column_physical_name="phone_number",
        source_column_datatype="VARCHAR(20)"
    )
    
    col_address = SourceColumn.objects.create(
        source_table=tbl_customers,
        source_column_physical_name="delivery_address",
        source_column_datatype="VARCHAR(500)"
    )
    
    col_customer_since = SourceColumn.objects.create(
        source_table=tbl_customers,
        source_column_physical_name="customer_since_date",
        source_column_datatype="DATE"
    )
    
    # Orders table
    tbl_orders = SourceTable.objects.create(
        project=project,
        source_system=src_ordering_app,
        physical_table_name="orders",
        record_source_value="PIZZA_APP",
        load_date_value="order_timestamp"
    )
    
    col_order_id = SourceColumn.objects.create(
        source_table=tbl_orders,
        source_column_physical_name="order_id",
        source_column_datatype="INTEGER"
    )
    
    col_order_customer_id = SourceColumn.objects.create(
        source_table=tbl_orders,
        source_column_physical_name="customer_id",
        source_column_datatype="INTEGER"
    )
    
    col_order_date = SourceColumn.objects.create(
        source_table=tbl_orders,
        source_column_physical_name="order_date",
        source_column_datatype="TIMESTAMP"
    )
    
    col_order_status = SourceColumn.objects.create(
        source_table=tbl_orders,
        source_column_physical_name="order_status",
        source_column_datatype="VARCHAR(50)"
    )
    
    col_total_amount = SourceColumn.objects.create(
        source_table=tbl_orders,
        source_column_physical_name="total_amount",
        source_column_datatype="DECIMAL(10,2)"
    )
    
    # Pizzas table
    tbl_pizzas = SourceTable.objects.create(
        project=project,
        source_system=src_ordering_app,
        physical_table_name="pizzas",
        record_source_value="PIZZA_APP",
        load_date_value="catalog_load_timestamp"
    )
    
    col_pizza_id = SourceColumn.objects.create(
        source_table=tbl_pizzas,
        source_column_physical_name="pizza_id",
        source_column_datatype="INTEGER"
    )
    
    col_pizza_name = SourceColumn.objects.create(
        source_table=tbl_pizzas,
        source_column_physical_name="pizza_name",
        source_column_datatype="VARCHAR(100)"
    )
    
    col_pizza_size = SourceColumn.objects.create(
        source_table=tbl_pizzas,
        source_column_physical_name="size",
        source_column_datatype="VARCHAR(20)"
    )
    
    col_pizza_toppings = SourceColumn.objects.create(
        source_table=tbl_pizzas,
        source_column_physical_name="toppings",
        source_column_datatype="VARCHAR(500)"
    )
    
    col_pizza_price = SourceColumn.objects.create(
        source_table=tbl_pizzas,
        source_column_physical_name="base_price",
        source_column_datatype="DECIMAL(8,2)"
    )
    
    # Order Items (link between orders and pizzas)
    tbl_order_items = SourceTable.objects.create(
        project=project,
        source_system=src_ordering_app,
        physical_table_name="order_items",
        record_source_value="PIZZA_APP",
        load_date_value="item_timestamp"
    )
    
    col_item_order_id = SourceColumn.objects.create(
        source_table=tbl_order_items,
        source_column_physical_name="order_id",
        source_column_datatype="INTEGER"
    )
    
    col_item_pizza_id = SourceColumn.objects.create(
        source_table=tbl_order_items,
        source_column_physical_name="pizza_id",
        source_column_datatype="INTEGER"
    )
    
    col_item_quantity = SourceColumn.objects.create(
        source_table=tbl_order_items,
        source_column_physical_name="quantity",
        source_column_datatype="INTEGER"
    )
    
    col_item_special_instructions = SourceColumn.objects.create(
        source_table=tbl_order_items,
        source_column_physical_name="special_instructions",
        source_column_datatype="VARCHAR(500)"
    )
    
    # === Delivery Tracker Tables ===
    
    # Drivers table
    tbl_drivers = SourceTable.objects.create(
        project=project,
        source_system=src_delivery_tracking,
        physical_table_name="drivers",
        record_source_value="DELIVERY_TRACKER",
        load_date_value="tracker_load_timestamp"
    )
    
    col_driver_id = SourceColumn.objects.create(
        source_table=tbl_drivers,
        source_column_physical_name="driver_id",
        source_column_datatype="INTEGER"
    )
    
    col_driver_name = SourceColumn.objects.create(
        source_table=tbl_drivers,
        source_column_physical_name="driver_name",
        source_column_datatype="VARCHAR(200)"
    )
    
    col_driver_license = SourceColumn.objects.create(
        source_table=tbl_drivers,
        source_column_physical_name="license_number",
        source_column_datatype="VARCHAR(50)"
    )
    
    col_driver_vehicle = SourceColumn.objects.create(
        source_table=tbl_drivers,
        source_column_physical_name="vehicle_type",
        source_column_datatype="VARCHAR(100)"
    )
    
    col_driver_rating = SourceColumn.objects.create(
        source_table=tbl_drivers,
        source_column_physical_name="avg_rating",
        source_column_datatype="DECIMAL(3,2)"
    )
    
    # Deliveries table
    tbl_deliveries = SourceTable.objects.create(
        project=project,
        source_system=src_delivery_tracking,
        physical_table_name="deliveries",
        record_source_value="DELIVERY_TRACKER",
        load_date_value="delivery_timestamp"
    )
    
    col_delivery_order_id = SourceColumn.objects.create(
        source_table=tbl_deliveries,
        source_column_physical_name="order_id",
        source_column_datatype="INTEGER"
    )
    
    col_delivery_driver_id = SourceColumn.objects.create(
        source_table=tbl_deliveries,
        source_column_physical_name="driver_id",
        source_column_datatype="INTEGER"
    )
    
    col_delivery_status = SourceColumn.objects.create(
        source_table=tbl_deliveries,
        source_column_physical_name="delivery_status",
        source_column_datatype="VARCHAR(50)"
    )
    
    col_delivery_time = SourceColumn.objects.create(
        source_table=tbl_deliveries,
        source_column_physical_name="estimated_delivery_time",
        source_column_datatype="TIMESTAMP"
    )
    
    col_delivery_actual_time = SourceColumn.objects.create(
        source_table=tbl_deliveries,
        source_column_physical_name="actual_delivery_time",
        source_column_datatype="TIMESTAMP"
    )
    
    # === CRM Tables ===
    
    # Customer profiles (additional customer data)
    tbl_crm_customers = SourceTable.objects.create(
        project=project,
        source_system=src_crm,
        physical_table_name="customer_profiles",
        record_source_value="CRM_MASTER",
        load_date_value="crm_sync_timestamp"
    )
    
    col_crm_customer_id = SourceColumn.objects.create(
        source_table=tbl_crm_customers,
        source_column_physical_name="customer_id",
        source_column_datatype="INTEGER"
    )
    
    col_crm_loyalty_tier = SourceColumn.objects.create(
        source_table=tbl_crm_customers,
        source_column_physical_name="loyalty_tier",
        source_column_datatype="VARCHAR(20)"
    )
    
    col_crm_total_orders = SourceColumn.objects.create(
        source_table=tbl_crm_customers,
        source_column_physical_name="total_lifetime_orders",
        source_column_datatype="INTEGER"
    )
    
    col_crm_preferences = SourceColumn.objects.create(
        source_table=tbl_crm_customers,
        source_column_physical_name="preferences",
        source_column_datatype="VARCHAR(1000)"
    )
    
    # ============================================================================
    # 3. HUBS
    # ============================================================================
    print("🎯 Creating hubs...")
    
    # Hub: Customer
    hub_customer = Hub.objects.create(
        project=project,
        group=group_customer,
        hub_physical_name="hub_customer",
        hub_type=Hub.HubType.STANDARD,
        hub_hashkey_name="hk_customer",
        create_record_tracking_satellite=True,
        create_effectivity_satellite=True
    )
    
    hub_col_customer_id = HubColumn.objects.create(
        hub=hub_customer,
        column_name="customer_id",
        column_type=HubColumn.ColumnType.BUSINESS_KEY,
        sort_order=1
    )
    
    HubSourceMapping.objects.create(
        hub_column=hub_col_customer_id,
        source_column=col_customer_id,
        is_primary_source=True
    )
    
    HubSourceMapping.objects.create(
        hub_column=hub_col_customer_id,
        source_column=col_order_customer_id,
        is_primary_source=False
    )
    
    # Hub: Order
    hub_order = Hub.objects.create(
        project=project,
        group=group_operations,
        hub_physical_name="hub_order",
        hub_type=Hub.HubType.STANDARD,
        hub_hashkey_name="hk_order",
        create_record_tracking_satellite=True,
        create_effectivity_satellite=False
    )
    
    hub_col_order_id = HubColumn.objects.create(
        hub=hub_order,
        column_name="order_id",
        column_type=HubColumn.ColumnType.BUSINESS_KEY,
        sort_order=1
    )
    
    HubSourceMapping.objects.create(
        hub_column=hub_col_order_id,
        source_column=col_order_id,
        is_primary_source=True
    )
    
    # Hub: Pizza
    hub_pizza = Hub.objects.create(
        project=project,
        group=group_product,
        hub_physical_name="hub_pizza",
        hub_type=Hub.HubType.STANDARD,
        hub_hashkey_name="hk_pizza",
        create_record_tracking_satellite=False,
        create_effectivity_satellite=False
    )
    
    hub_col_pizza_id = HubColumn.objects.create(
        hub=hub_pizza,
        column_name="pizza_id",
        column_type=HubColumn.ColumnType.BUSINESS_KEY,
        sort_order=1
    )
    
    HubSourceMapping.objects.create(
        hub_column=hub_col_pizza_id,
        source_column=col_pizza_id,
        is_primary_source=True
    )
    
    # Hub: Driver
    hub_driver = Hub.objects.create(
        project=project,
        group=group_operations,
        hub_physical_name="hub_driver",
        hub_type=Hub.HubType.STANDARD,
        hub_hashkey_name="hk_driver",
        create_record_tracking_satellite=True,
        create_effectivity_satellite=True
    )
    
    hub_col_driver_id = HubColumn.objects.create(
        hub=hub_driver,
        column_name="driver_id",
        column_type=HubColumn.ColumnType.BUSINESS_KEY,
        sort_order=1
    )
    
    HubSourceMapping.objects.create(
        hub_column=hub_col_driver_id,
        source_column=col_driver_id,
        is_primary_source=True
    )
    
    # ============================================================================
    # 4. LINKS
    # ============================================================================
    print("🔗 Creating links...")
    
    # Link: Customer-Order
    link_customer_order = Link.objects.create(
        project=project,
        group=group_operations,
        link_physical_name="link_customer_order",
        link_type=Link.LinkType.STANDARD,
        link_hashkey_name="lk_customer_order"
    )
    link_customer_order.hub_references.add(hub_customer, hub_order)
    
    link_col_customer_fk = LinkColumn.objects.create(
        link=link_customer_order,
        column_name="customer_fk",
        column_type=LinkColumn.ColumnType.BUSINESS_KEY,
        sort_order=1
    )
    
    link_col_order_fk = LinkColumn.objects.create(
        link=link_customer_order,
        column_name="order_fk",
        column_type=LinkColumn.ColumnType.BUSINESS_KEY,
        sort_order=2
    )
    
    LinkSourceMapping.objects.create(
        link_column=link_col_customer_fk,
        source_column=col_order_customer_id,
        is_primary_source=True
    )
    
    LinkSourceMapping.objects.create(
        link_column=link_col_order_fk,
        source_column=col_order_id,
        is_primary_source=True
    )
    
    # Link: Order-Pizza
    link_order_pizza = Link.objects.create(
        project=project,
        group=group_operations,
        link_physical_name="link_order_pizza",
        link_type=Link.LinkType.STANDARD,
        link_hashkey_name="lk_order_pizza"
    )
    link_order_pizza.hub_references.add(hub_order, hub_pizza)
    
    link_col_order_pizza_order_fk = LinkColumn.objects.create(
        link=link_order_pizza,
        column_name="order_fk",
        column_type=LinkColumn.ColumnType.BUSINESS_KEY,
        sort_order=1
    )
    
    link_col_order_pizza_pizza_fk = LinkColumn.objects.create(
        link=link_order_pizza,
        column_name="pizza_fk",
        column_type=LinkColumn.ColumnType.BUSINESS_KEY,
        sort_order=2
    )
    
    link_col_quantity = LinkColumn.objects.create(
        link=link_order_pizza,
        column_name="quantity",
        column_type=LinkColumn.ColumnType.PAYLOAD,
        sort_order=3
    )
    
    LinkSourceMapping.objects.create(
        link_column=link_col_order_pizza_order_fk,
        source_column=col_item_order_id,
        is_primary_source=True
    )
    
    LinkSourceMapping.objects.create(
        link_column=link_col_order_pizza_pizza_fk,
        source_column=col_item_pizza_id,
        is_primary_source=True
    )
    
    LinkSourceMapping.objects.create(
        link_column=link_col_quantity,
        source_column=col_item_quantity,
        is_primary_source=True
    )
    
    # Link: Delivery (Order-Driver)
    link_delivery = Link.objects.create(
        project=project,
        group=group_operations,
        link_physical_name="link_delivery",
        link_type=Link.LinkType.STANDARD,
        link_hashkey_name="lk_delivery"
    )
    link_delivery.hub_references.add(hub_order, hub_driver)
    
    link_col_delivery_order_fk = LinkColumn.objects.create(
        link=link_delivery,
        column_name="order_fk",
        column_type=LinkColumn.ColumnType.BUSINESS_KEY,
        sort_order=1
    )
    
    link_col_delivery_driver_fk = LinkColumn.objects.create(
        link=link_delivery,
        column_name="driver_fk",
        column_type=LinkColumn.ColumnType.BUSINESS_KEY,
        sort_order=2
    )
    
    LinkSourceMapping.objects.create(
        link_column=link_col_delivery_order_fk,
        source_column=col_delivery_order_id,
        is_primary_source=True
    )
    
    LinkSourceMapping.objects.create(
        link_column=link_col_delivery_driver_fk,
        source_column=col_delivery_driver_id,
        is_primary_source=True
    )
    
    # ============================================================================
    # 5. SATELLITES
    # ============================================================================
    print("🛰️  Creating satellites...")
    
    # === Customer Satellites ===
    
    # Standard Satellite: Customer Details
    sat_customer_details = Satellite.objects.create(
        project=project,
        group=group_customer,
        satellite_physical_name="sat_customer_details",
        satellite_type=Satellite.SatelliteType.STANDARD,
        parent_hub=hub_customer,
        source_table=tbl_customers
    )
    
    SatelliteColumn.objects.create(
        satellite=sat_customer_details,
        source_column=col_customer_name,
        target_column_name="customer_name",
        is_multi_active_key=False,
        include_in_delta_detection=True
    )
    
    SatelliteColumn.objects.create(
        satellite=sat_customer_details,
        source_column=col_email,
        target_column_name="email_address",
        is_multi_active_key=False,
        include_in_delta_detection=True
    )
    
    SatelliteColumn.objects.create(
        satellite=sat_customer_details,
        source_column=col_phone,
        target_column_name="phone_number",
        is_multi_active_key=False,
        include_in_delta_detection=True
    )
    
    SatelliteColumn.objects.create(
        satellite=sat_customer_details,
        source_column=col_customer_since,
        target_column_name="member_since_date",
        is_multi_active_key=False,
        include_in_delta_detection=False  # Not included in hashdiff
    )
    
    # Multi-Active Satellite: Customer Addresses (customers can have multiple addresses)
    sat_customer_addresses = Satellite.objects.create(
        project=project,
        group=group_customer,
        satellite_physical_name="sat_customer_addresses",
        satellite_type=Satellite.SatelliteType.MULTI_ACTIVE,
        parent_hub=hub_customer,
        source_table=tbl_customers
    )
    
    SatelliteColumn.objects.create(
        satellite=sat_customer_addresses,
        source_column=col_address,
        target_column_name="address_text",
        is_multi_active_key=True,  # Address is the multi-active key
        include_in_delta_detection=True
    )
    
    # Reference Satellite: Customer Loyalty (from CRM)
    sat_customer_loyalty = Satellite.objects.create(
        project=project,
        group=group_customer,
        satellite_physical_name="sat_customer_loyalty",
        satellite_type=Satellite.SatelliteType.REFERENCE,
        parent_hub=hub_customer,
        source_table=tbl_crm_customers
    )
    
    SatelliteColumn.objects.create(
        satellite=sat_customer_loyalty,
        source_column=col_crm_loyalty_tier,
        target_column_name="loyalty_tier",
        is_multi_active_key=False,
        include_in_delta_detection=True
    )
    
    SatelliteColumn.objects.create(
        satellite=sat_customer_loyalty,
        source_column=col_crm_total_orders,
        target_column_name="lifetime_order_count",
        is_multi_active_key=False,
        include_in_delta_detection=True
    )
    
    SatelliteColumn.objects.create(
        satellite=sat_customer_loyalty,
        source_column=col_crm_preferences,
        target_column_name="customer_preferences",
        is_multi_active_key=False,
        include_in_delta_detection=False
    )
    
    # === Order Satellites ===
    
    # Standard Satellite: Order Details
    sat_order_details = Satellite.objects.create(
        project=project,
        group=group_operations,
        satellite_physical_name="sat_order_details",
        satellite_type=Satellite.SatelliteType.STANDARD,
        parent_hub=hub_order,
        source_table=tbl_orders
    )
    
    SatelliteColumn.objects.create(
        satellite=sat_order_details,
        source_column=col_order_date,
        target_column_name="order_timestamp",
        is_multi_active_key=False,
        include_in_delta_detection=True
    )
    
    SatelliteColumn.objects.create(
        satellite=sat_order_details,
        source_column=col_order_status,
        target_column_name="order_status",
        is_multi_active_key=False,
        include_in_delta_detection=True
    )
    
    SatelliteColumn.objects.create(
        satellite=sat_order_details,
        source_column=col_total_amount,
        target_column_name="total_order_amount",
        is_multi_active_key=False,
        include_in_delta_detection=True
    )
    
    # === Pizza Satellites ===
    
    # Non-Historized Satellite: Pizza Recipe (changes don't need history)
    sat_pizza_recipe = Satellite.objects.create(
        project=project,
        group=group_product,
        satellite_physical_name="sat_pizza_recipe",
        satellite_type=Satellite.SatelliteType.NON_HISTORIZED,
        parent_hub=hub_pizza,
        source_table=tbl_pizzas
    )
    
    SatelliteColumn.objects.create(
        satellite=sat_pizza_recipe,
        source_column=col_pizza_name,
        target_column_name="pizza_name",
        is_multi_active_key=False,
        include_in_delta_detection=True
    )
    
    SatelliteColumn.objects.create(
        satellite=sat_pizza_recipe,
        source_column=col_pizza_size,
        target_column_name="size",
        is_multi_active_key=False,
        include_in_delta_detection=True
    )
    
    SatelliteColumn.objects.create(
        satellite=sat_pizza_recipe,
        source_column=col_pizza_toppings,
        target_column_name="topping_list",
        is_multi_active_key=False,
        include_in_delta_detection=True
    )
    
    SatelliteColumn.objects.create(
        satellite=sat_pizza_recipe,
        source_column=col_pizza_price,
        target_column_name="base_price",
        is_multi_active_key=False,
        include_in_delta_detection=True
    )
    
    # === Driver Satellites ===
    
    # Standard Satellite: Driver Info
    sat_driver_info = Satellite.objects.create(
        project=project,
        group=group_operations,
        satellite_physical_name="sat_driver_info",
        satellite_type=Satellite.SatelliteType.STANDARD,
        parent_hub=hub_driver,
        source_table=tbl_drivers
    )
    
    SatelliteColumn.objects.create(
        satellite=sat_driver_info,
        source_column=col_driver_name,
        target_column_name="driver_name",
        is_multi_active_key=False,
        include_in_delta_detection=True
    )
    
    SatelliteColumn.objects.create(
        satellite=sat_driver_info,
        source_column=col_driver_license,
        target_column_name="license_number",
        is_multi_active_key=False,
        include_in_delta_detection=True
    )
    
    SatelliteColumn.objects.create(
        satellite=sat_driver_info,
        source_column=col_driver_vehicle,
        target_column_name="vehicle_description",
        is_multi_active_key=False,
        include_in_delta_detection=True
    )
    
    SatelliteColumn.objects.create(
        satellite=sat_driver_info,
        source_column=col_driver_rating,
        target_column_name="average_rating",
        is_multi_active_key=False,
        include_in_delta_detection=True
    )
    
    # === Link Satellites ===
    
    # Satellite on Order-Pizza Link: Order Item Details
    sat_order_item_details = Satellite.objects.create(
        project=project,
        group=group_operations,
        satellite_physical_name="sat_order_item_details",
        satellite_type=Satellite.SatelliteType.STANDARD,
        parent_link=link_order_pizza,
        source_table=tbl_order_items
    )
    
    SatelliteColumn.objects.create(
        satellite=sat_order_item_details,
        source_column=col_item_special_instructions,
        target_column_name="special_instructions",
        is_multi_active_key=False,
        include_in_delta_detection=True
    )
    
    # Satellite on Delivery Link: Delivery Tracking
    sat_delivery_tracking = Satellite.objects.create(
        project=project,
        group=group_operations,
        satellite_physical_name="sat_delivery_tracking",
        satellite_type=Satellite.SatelliteType.STANDARD,
        parent_link=link_delivery,
        source_table=tbl_deliveries
    )
    
    SatelliteColumn.objects.create(
        satellite=sat_delivery_tracking,
        source_column=col_delivery_status,
        target_column_name="delivery_status",
        is_multi_active_key=False,
        include_in_delta_detection=True
    )
    
    SatelliteColumn.objects.create(
        satellite=sat_delivery_tracking,
        source_column=col_delivery_time,
        target_column_name="estimated_delivery_time",
        is_multi_active_key=False,
        include_in_delta_detection=True
    )
    
    SatelliteColumn.objects.create(
        satellite=sat_delivery_tracking,
        source_column=col_delivery_actual_time,
        target_column_name="actual_delivery_time",
        is_multi_active_key=False,
        include_in_delta_detection=True
    )
    
    # ============================================================================
    # 6. REFERENCE TABLE (Country Reference Data)
    # ============================================================================
    print("🔖 Creating reference table...")
    
    from engine.models import ReferenceTable, ReferenceTableSatelliteAssignment
    
    # Step 1: Create REFERENCE HUB for countries
    # Reference hubs are used for lookup/reference data that doesn't change frequently
    hub_country = Hub.objects.create(
        project=project,
        hub_physical_name="hub_country",
        hub_type=Hub.HubType.REFERENCE,  # This is a REFERENCE hub, not STANDARD
        group=group_customer
    )
    
    # Hub business key
    HubColumn.objects.create(
        hub=hub_country,
        column_name="country_code",
        column_type=HubColumn.ColumnType.BUSINESS_KEY,
        sort_order=1
    )
    
    # Step 2: Create REFERENCE SATELLITE for country attributes
    # Reference satellites contain descriptive attributes for reference data
    sat_country_details = Satellite.objects.create(
        project=project,
        satellite_physical_name="sat_country_details",
        satellite_type=Satellite.SatelliteType.REFERENCE,  # This is a REFERENCE satellite
        parent_hub=hub_country,
        group=group_customer
    )
    
    # Add country attribute columns
    SatelliteColumn.objects.create(
        satellite=sat_country_details,
        satellite_column_physical_name="country_name",
        satellite_column_datatype="VARCHAR(100)",
        is_multi_active_key=False,
        include_in_delta_detection=True
    )
    
    SatelliteColumn.objects.create(
        satellite=sat_country_details,
        satellite_column_physical_name="country_region",
        satellite_column_datatype="VARCHAR(50)",
        is_multi_active_key=False,
        include_in_delta_detection=True
    )
    
    SatelliteColumn.objects.create(
        satellite=sat_country_details,
        satellite_column_physical_name="country_currency",
        satellite_column_datatype="VARCHAR(3)",
        is_multi_active_key=False,
        include_in_delta_detection=True
    )
    
    # Step 3: Create REFERENCE TABLE
    # Reference tables combine reference hubs with their satellites for easy querying
    ref_country = ReferenceTable.objects.create(
        project=project,
        reference_table_physical_name="ref_country",
        reference_hub=hub_country,  # Must reference a REFERENCE hub
        historization_type=ReferenceTable.HistorizationType.LATEST  # Show only latest values
    )
    
    # Step 4: Assign satellite to reference table
    ReferenceTableSatelliteAssignment.objects.create(
        reference_table=ref_country,
        reference_satellite=sat_country_details  # Must be a REFERENCE satellite
    )
    
    print(f"   ✓ Created reference hub: {hub_country.hub_physical_name}")
    print(f"   ✓ Created reference satellite: {sat_country_details.satellite_physical_name}")
    print(f"   ✓ Created reference table: {ref_country.reference_table_physical_name}")
    
    # ============================================================================
    # 7. PIT STRUCTURE
    # ============================================================================
    print("⏰ Creating PIT structure...")
    
    from engine.models import PIT
    
    # Create PIT for customer hub
    pit = PIT.objects.create(
        project=project,
        pit_physical_name="pit_customer_details",
        tracked_entity_type=PIT.TrackedEntityType.HUB,
        tracked_hub=hub_customer,
        snapshot_control_table=snapshot_control,
        snapshot_control_logic=daily_logic,
        dimension_key_column_name="customer_key",
        use_snapshot_optimization=True,
        include_business_objects_before_appearance=False
    )
    
    # Add satellites to PIT
    pit.satellites.add(sat_customer_details, sat_customer_addresses)
    
    print(f"   ✓ Created PIT: {pit.pit_physical_name}")
    print(f"     Tracking: {pit.tracked_hub.hub_physical_name}")
    print(f"     Satellites: {pit.satellites.count()}")
    
    # ============================================================================
    # SUMMARY
    # ============================================================================
    print("\n" + "="*70)
    print("✅ Pizza Delivery Empire Data Vault Created Successfully!")
    print("="*70)
    print(f"\n📊 Summary:")
    print(f"   Project: {project.name}")
    print(f"   Groups: {Group.objects.filter(project=project).count()}")
    print(f"   Source Systems: {SourceSystem.objects.filter(project=project).count()}")
    print(f"   Source Tables: {SourceTable.objects.filter(project=project).count()}")
    print(f"   Source Columns: {SourceColumn.objects.count()}")
    print(f"   Hubs: {Hub.objects.filter(project=project).count()}")
    print(f"   Links: {Link.objects.filter(project=project).count()}")
    print(f"   Satellites: {Satellite.objects.filter(project=project).count()}")
    print(f"      - Standard: {Satellite.objects.filter(project=project, satellite_type='standard').count()}")
    print(f"      - Multi-Active: {Satellite.objects.filter(project=project, satellite_type='multi_active').count()}")
    print(f"      - Non-Historized: {Satellite.objects.filter(project=project, satellite_type='non_historized').count()}")
    print(f"      - Reference: {Satellite.objects.filter(project=project, satellite_type='reference').count()}")
    print(f"   Reference Tables: {ReferenceTable.objects.filter(project=project).count()}")
    print(f"   PITs: {PIT.objects.filter(project=project).count()}")
    
    print(f"\n🍕 Sample Entities:")
    print(f"   - Hubs: Customer, Order, Pizza, Driver")
    print(f"   - Links: Customer-Order, Order-Pizza, Delivery (Order-Driver)")
    print(f"   - Satellites:")
    print(f"      • Customer Details (standard)")
    print(f"      • Customer Addresses (multi-active)")
    print(f"      • Customer Loyalty (reference)")
    print(f"      • Order Details (standard)")
    print(f"      • Pizza Recipe (non-historized)")
    print(f"      • Driver Info (standard)")
    print(f"      • Order Item Details (on link, standard)")
    print(f"      • Delivery Tracking (on link, standard)")
    
    print(f"\n🎯 To export this model, run:")
    print(f"   turbovault run --project {project.name}")
    
    print(f"\n🌐 To view in admin:")
    print(f"   turbovault serve")
    print(f"   Then open: http://127.0.0.1:8000/admin/")
    print("\n")


if __name__ == "__main__":
    # Clear existing data for this project if it exists
    try:
        existing_project = Project.objects.get(name="pizza_delivery_empire")
        print(f"⚠️  Project 'pizza_delivery_empire' already exists. Deleting...")
        existing_project.delete()
        print("✓ Existing project deleted.\n")
    except Project.DoesNotExist:
        pass
    
    # Create the sample data
    create_pizza_delivery_project()
    print("🎉 All done! Ready to explore your Pizza Delivery Empire Data Vault!\n")
