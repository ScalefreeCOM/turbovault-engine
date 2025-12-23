# Sample Data Scripts

This directory contains scripts for populating the TurboVault Engine database with sample data.

## 🍕 Pizza Delivery Empire

**File:** `populate_sample_data.py`

An example demonstrating a complete Data Vault model for a fictional pizza delivery business.

### What It Creates

**Project:** `pizza_delivery_empire`

**3 Groups:**
- `customer_domain` - Customer-related entities
- `product_domain` - Product catalog entities  
- `operations_domain` - Operational entities

**4 Hubs:**
- `hub_customer` - Customer business entity
- `hub_order` - Order business entity
- `hub_pizza` - Pizza product entity
- `hub_driver` - Delivery driver entity

**3 Links:**
- `link_customer_order` - Connects customers to their orders
- `link_order_pizza` - Connects orders to pizzas (order items)
- `link_delivery` - Connects orders to drivers (deliveries)

**8 Satellites:**
- `sat_customer_details` (standard) - Customer name, email, phone
- `sat_customer_addresses` (multi-active) - Multiple customer addresses
- `sat_customer_loyalty` (reference) - CRM loyalty tier and preferences
- `sat_order_details` (standard) - Order date, status, amount
- `sat_pizza_recipe` (non-historized) - Pizza name, size, toppings, price
- `sat_driver_info` (standard) - Driver name, license, vehicle, rating
- `sat_order_item_details` (standard, on link) - Special instructions
- `sat_delivery_tracking` (standard, on link) - Delivery status and times

**3 Source Systems:**
- `PizzaOrderApp` - Online ordering application
- `DeliveryTracker` - Delivery tracking system
- `CustomerCRM` - Customer relationship management system

**7 Source Tables with 42 columns total**

### Running the Script

```bash
# From the repository root
python scripts/populate_sample_data.py
```

The script will:
1. Delete any existing `pizza_delivery_empire` project
2. Create all entities with proper mappings
3. Display a summary of what was created

### After Running

**Export the model:**
```bash
turbovault run --project pizza_delivery_empire
```

**View in Django Admin:**
```bash
turbovault serve
# Open http://127.0.0.1:8000/admin/
```

### What You Can Learn

This sample demonstrates:
- ✅ Multiple hub types (standard)
- ✅ Multi-active satellites (customer can have multiple addresses)
- ✅ Reference satellites (data from CRM)
- ✅ Non-historized satellites (pizza recipes don't need history)
- ✅ Link satellites (order item details, delivery tracking)
- ✅ Multi-source hubs (customer business key from multiple tables)
- ✅ Links with payload columns (quantity in order-pizza link)
- ✅ Groups for organizing entities
- ✅ Complete source-to-target mappings

---

## Creating Your Own Sample Data

To create your own sample data script:

1. Copy `populate_sample_data.py` as a template
2. Modify the entities to match your use case
3. Run the script to populate your database

The script structure is:
1. **Setup Django** - Import models
2. **Create Project & Groups** - Logical organization
3. **Create Source Systems** - Define data sources
4. **Create Source Tables & Columns** - Metadata
5. **Create Hubs** - Business entities
6. **Create Links** - Relationships
7. **Create Satellites** - Descriptive attributes
8. **Map everything together** - Source mappings

Happy modeling! 🍕
