"""Broad resale taxonomy; unrecognized product classes are kept as Other."""
CATEGORIES=['Laptop','Monitor','Phone','Tablet','Computer','Audio','Camera','Gaming','Electronics','Appliance','Furniture','Clothing','Shoes','Accessory','Jewelry','Watch','Sports','Tools','Books','Toys','Home','Garden','Vehicle','Parts','Collectible','Other']

def normalize_category(value):
    text=str(value or '').strip()
    aliases={'smartphone':'Phone','headphones':'Audio','speaker':'Audio','book':'Books','toy':'Toys','chair':'Furniture','clothes':'Clothing','footwear':'Shoes','accessories':'Accessory'}
    return next((c for c in CATEGORIES if c.lower()==text.lower()),aliases.get(text.lower(),'Other'))
