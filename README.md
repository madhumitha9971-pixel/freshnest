# 🌿 FreshNest
### Online Vegetable Shopping Application

FreshNest is a responsive vegetable-shopping application built with Python, Flask, SQLite, HTML, CSS and JavaScript.

Customers can browse vegetables, manage a shopping cart, enter delivery details and place demonstration orders. An admin interface supports inventory and order-status management.

> Educational prototype: no real payments are collected and no actual deliveries are dispatched.

---

## 📌 Project Overview

FreshNest demonstrates an online vegetable-shopping workflow:

**Browse → Add to Cart → Sign In → Enter Delivery Details → Review → Place Demo Order → Track Status**

The application was developed and demonstrated using Google Colab.

---

## ✨ Features

### Customer Accounts
- Register using a name, mobile number and password.
- Sign in using a registered mobile number and password.
- Password hashing.
- Account-specific order history.
- Logout functionality.

### Product Catalogue
- Vegetable browsing.
- Product images or illustrated fallbacks.
- Search by product name.
- Category filtering.
- Price sorting.
- Product-detail view.
- Browser-local wishlist.

### Shopping Cart
- Add vegetables to the cart.
- Increase or decrease quantities.
- Remove products.
- Clear the cart.
- View subtotal, delivery fee and total.

### Checkout
- Recipient name and mobile number.
- Address, locality, city and PIN code.
- Preferred delivery date and time slot.
- Order review before confirmation.
- Unique order ID.
- Demo cash-on-delivery workflow.

### Order Tracking
Customers can view the latest admin-updated status:

`Confirmed → Packed → Out for delivery → Delivered`

This is manual status tracking, not live GPS tracking.

### Admin Controls
- View customer orders.
- Update order status.
- Manage available stock.
- View customer and order counts.
- View total order value.

Order value is not collected revenue. The prototype does not collect payments.

---

## 🍲 Cook-to-Cart

Cook-to-Cart helps customers build a vegetable basket for a selected dish.

### Workflow
1. Choose a recipe.
2. Select the number of servings.
3. Review suggested vegetable quantities.
4. Add the vegetables to the cart.
5. Adjust quantities before checkout.

Example baskets:
- Vegetable kurma.
- Crunchy salad.
- Sambar vegetables.

Only the listed vegetables are included. Spices, oil, rice, lentils and other pantry ingredients are not included.

This feature uses predefined recipe rules and quantity calculations, not an AI model.

---

## 🛠️ Technology Stack

| Component | Technology |
|---|---|
| Language | Python |
| Backend | Flask |
| Database | SQLite |
| Frontend | HTML, CSS and JavaScript |
| Authentication | Sessions and password hashing |
| Development | Google Colab |
| Temporary demo access | Cloudflare Tunnel |

---

## 📁 Project Structure

```text
freshnest/
├── README.md
├── freshnest.py
├── FreshNest_Colab.ipynb
├── requirements.txt
├── .gitignore
└── screenshots/
    ├── home.png
    ├── products.png
    ├── cart.png
    ├── checkout.png
    ├── orders.png
    └── admin.png
```

### File Details
- `freshnest.py`: application source code.
- `FreshNest_Colab.ipynb`: installation and demonstration notebook.
- `requirements.txt`: Python dependencies.
- `.gitignore`: private and generated files excluded from version control.
- `screenshots/`: screenshots of the working application.

---

## 🚀 Run in Google Colab

1. Open `FreshNest_Colab.ipynb` in Google Colab.
2. Run the dependency-installation cell.
3. Run the application-creation cell.
4. Run the server and tunnel startup cell.
5. Open the public URL displayed in the output.

Keep the Colab runtime connected while using the temporary website.

The tunnel address and runtime storage are temporary. Back up important test data privately.

### Python Dependencies

If `requirements.txt` has been uploaded to the runtime:

```bash
pip install -r requirements.txt
```

Cloudflare Tunnel is downloaded separately as an executable. It should not be installed with `pip install cloudflared`.

---

## 🔐 Accounts

### Customer
Create an account through the signup screen using test details.

Do not reuse a personal password.

### Admin
Use the configured admin credentials displayed by the Colab startup cell.

Do not publish admin passwords in screenshots, README files or notebook outputs.

---

## 🧪 Testing Checklist

- [ ] Create a test customer account.
- [ ] Log out and sign in again.
- [ ] Search for a vegetable.
- [ ] Filter and sort products.
- [ ] Add products to the cart.
- [ ] Update quantities and verify totals.
- [ ] Try a recipe basket.
- [ ] Enter delivery details.
- [ ] Review and place a demo order.
- [ ] Check order history.
- [ ] Sign in as admin.
- [ ] Update stock and order status.
- [ ] Refresh the customer order status.

---

## ⚠️ Limitations

- Prices, discounts and inventory are sample data.
- No online payments are processed.
- No actual deliveries are booked.
- Mobile numbers are not verified using SMS OTP.
- Tracking depends on manual admin updates.
- Recipe suggestions are rule-based.
- Image availability depends on the source configuration.
- Colab is a temporary demonstration environment.
- The app is not a security-audited commercial shop.

Use test customer details only.

---

## 🗺️ Future Improvements

These are planned ideas, not implemented features:

- English and Tamil language support.
- SMS verification and account recovery.
- Multiple saved addresses.
- Delivery-serviceable PIN-code validation.
- Real payment-provider integration.
- Farmer listings with admin approval.
- Weekly vegetable subscriptions.
- Delivery-partner management.
- Permanent hosting and PWA installation support.

---

## 🔒 Privacy and Security

Never commit:
- Private configuration files.
- Admin passwords.
- API tokens.
- Customer databases.
- Delivery addresses.
- Payment information.

Before real customer use, review authentication, account recovery, backups, data retention, checkout retry handling and operational delivery processes.

---

## 📚 Project Status

FreshNest is an educational e-commerce prototype.

Uploading the source to GitHub does not automatically deploy the Flask backend.

---

## 👤 Maintainer

Name: YOUR NAME  
GitHub: YOUR GITHUB USERNAME