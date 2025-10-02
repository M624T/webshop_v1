# Online Do'kon - E-commerce Web Application

## Overview
This is a Flask-based e-commerce web application with product management, shopping cart, checkout functionality, and AI chat support. The application was imported from GitHub and configured to run on Replit.

## Project Architecture

### Technology Stack
- **Backend**: Python 3.11 + Flask
- **Database**: SQLite (database/shop.db)
- **Frontend**: HTML, CSS, JavaScript
- **PDF Generation**: ReportLab
- **AI Chat**: Ollama (for product support)
- **Production Server**: Gunicorn

### Project Structure
```
├── app.py                  # Main Flask application
├── database/
│   └── shop.db            # SQLite database
├── static/
│   ├── images/            # Product images and media
│   ├── fonts/             # Custom fonts for PDF generation
│   ├── styles.css         # Global styles
│   └── favicon.ico        # Site icon
├── templates/             # HTML templates
│   ├── index.html         # Homepage
│   ├── product.html       # Product detail page
│   ├── cart.html          # Shopping cart
│   ├── checkout.html      # Checkout page
│   ├── success.html       # Order success page
│   ├── chat.html          # AI chat interface
│   ├── admin_add_product.html
│   └── admin_edit_product.html
└── requirements.txt       # Python dependencies
```

### Database Schema
The SQLite database contains two main tables:

1. **products**
   - id (PRIMARY KEY)
   - name
   - price
   - description
   - stock
   - image (comma-separated filenames)
   - videos (comma-separated video filenames)

2. **orders**
   - id (PRIMARY KEY)
   - name
   - phone
   - address
   - location (geo coordinates)
   - products (formatted product list)
   - total_price

## Features

### Customer-Facing
- Product catalog with pagination
- Product detail pages with image galleries
- Shopping cart with quantity management
- Checkout with geolocation support
- Order success page with PDF receipt download
- AI-powered chat support for product inquiries

### Admin Features
- Add new products with images and videos
- Edit existing products with drag-and-drop reordering
- Delete products
- **Enhanced Admin UX (Oct 2, 2025)**:
  - Interactive help tooltips (?) for every form field
  - Separate description images from product gallery images
  - Description images shown in list format with preview and embed code
  - Support for embedding images in descriptions using `{filename.jpg}` syntax
  - Fully responsive design for all devices
  - Visual feedback for all actions

### API Endpoints
- `/api/products` - Get products with pagination
- `/api/add-to-cart/<id>` - Add product to cart
- `/api/cart` - Get cart contents
- `/api/checkout` - Process checkout
- `/api/reverse` - Reverse geocode coordinates
- `/api/chat` - Chat with AI assistant

## Configuration

### Development
- Server runs on: `0.0.0.0:5000`
- Debug mode: Enabled
- CORS: Enabled for cross-origin requests
- Flask development server

### Production (Deployment)
- Server: Gunicorn
- Deployment type: Autoscale
- Command: `gunicorn --bind=0.0.0.0:5000 --reuse-port app:app`

## Recent Changes
- **2025-10-02**: Admin Panel UX Enhancement
  - Completely redesigned admin_add_product.html with modern UX
  - Completely redesigned admin_edit_product.html with modern UX
  - Added interactive help tooltips (?) for each form field
  - Separated description images from product gallery images
  - Description images now show in list format with preview and embed code
  - Fixed backend to prevent mixing description images with product images
  - Added full responsive design for mobile, tablet, and desktop
  - Added clear instructions for embedding images using {filename.jpg} syntax

- **2025-10-02**: Imported from GitHub and configured for Replit
  - Installed Python 3.11 and all dependencies
  - Updated app.py to bind to port 5000
  - Configured Flask workflow to run on port 5000
  - Set up deployment with Gunicorn
  - Updated .gitignore for Python projects
  - Created documentation

## Dependencies
See `requirements.txt` for full list. Key packages:
- Flask >= 3.0
- Flask-Cors >= 4.0
- requests >= 2.31.0
- ollama >= 0.2.0
- reportlab
- qrcode
- Pillow
- gunicorn

## Notes
- The application uses session-based shopping cart
- Images and videos are stored in `static/images/`
- PDF receipts include QR codes with order information
- Chat feature requires Ollama to be running (currently returns echo response as fallback)
