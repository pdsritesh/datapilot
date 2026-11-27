# Execution Accuracy — v3_with_retry

- **Run at:** 2026-11-27 10:34
- **Scoring mode:** lenient
- **Cases:** 90 · **Repeats per case:** 1 · **Total runs:** 90
- **Passed:** 81 · **Failed:** 9
- **Time:** 885.6s

## >>> EXECUTION ACCURACY: 90.0% (81/90) <<<

## 9 case(s) with at least one failing run

### [0/1] `avg_order_amount_sample_city`
- **query:** what is the average order amount for customers in Lucknow?
- **reason:** mismatch — got [('Krishna Sharma', 1280.0677777777778), ('Kavya Kumar', 1678.3408333333334), ('Aadhya Pillai', 4018.52)]..., expected [(1971.396551724138,)]...
- **pipeline's SQL:**

```sql
SELECT c.name, AVG(o.amount) AS avg_order_amount FROM customers AS c JOIN orders AS o ON c.customer_id = o.customer_id WHERE c.city = 'Lucknow' GROUP BY c.customer_id LIMIT 100
```

### [0/1] `top_3_customers_by_orders`
- **query:** who are the top 3 customers by number of orders?
- **reason:** mismatch — got [(23, 'Anika Kumar', 15), (48, 'Kabir Reddy', 15), (64, 'Aryan Das', 15)]..., expected [('Ishaan Nair', 15), ('Aarav Rao', 15), ('Aryan Das', 15)]...
- **pipeline's SQL:**

```sql
SELECT c.customer_id, c.name, COUNT(o.order_id) AS order_count FROM customers AS c JOIN orders AS o ON c.customer_id = o.customer_id GROUP BY c.customer_id, c.name ORDER BY order_count DESC LIMIT 3
```

### [0/1] `cheapest_5_orders`
- **query:** what are the 5 smallest individual orders?
- **reason:** expected a result, got type='clarify': 

### [0/1] `top_3_items_by_frequency`
- **query:** what are the 3 most frequently ordered items?
- **reason:** expected a result, got type='clarify': 

### [0/1] `did_sample_customer_buy_item`
- **query:** has Krishna Sharma ever ordered Kids Story Set?
- **reason:** expected a result, got type='error': That doesn't look related to the mall purchase data. Try asking about customers, orders, revenue or cities.

### [0/1] `customers_with_no_orders`
- **query:** are there any customers who have never placed an order?
- **reason:** mismatch — got []..., expected [(0,)]...
- **pipeline's SQL:**

```sql
SELECT c.customer_id, c.name, c.email, c.city FROM customers AS c LEFT JOIN orders AS o ON c.customer_id = o.customer_id WHERE o.order_id IS NULL LIMIT 100
```

### [0/1] `top_customer_in_sample_city`
- **query:** who is the top spender among customers in Lucknow?
- **reason:** expected a result, got type='clarify': 

### [0/1] `most_recent_order_item`
- **query:** what item was in the most recent order?
- **reason:** mismatch — got [('Kids Story Set',)]..., expected [('Kids Story Set', '2026-08-23')]...
- **pipeline's SQL:**

```sql
SELECT item_name FROM orders ORDER BY order_date DESC LIMIT 1
```

### [0/1] `list_orders_sample_category`
- **query:** list all orders in the Books category
- **reason:** mismatch — got [(1, 'Kids Story Set', 'Books', 1, 1056.43, '2026-05-01'), (8, 'Cookbook', 'Books', 3, 555.98, '2026-03-07'), (9, 'Fiction Novel', 'Books', 2, 573.89, '2025-12-07')]..., expected [(1, 'Kids Story Set', 1056.43), (8, 'Cookbook', 555.98), (9, 'Fiction Novel', 573.89)]...
- **pipeline's SQL:**

```sql
SELECT order_id, item_name, category, quantity, amount, order_date FROM orders WHERE category = 'Books' LIMIT 100
```
