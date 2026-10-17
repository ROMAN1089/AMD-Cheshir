"""Seller-owned product photography. Re-encode pixels; never retain upload metadata."""
import io
import math
from pathlib import Path
from uuid import uuid4
from PIL import Image, ImageOps, UnidentifiedImageError
import store

Image.MAX_IMAGE_PIXELS = 24_000_000
LIMIT = 12 * 1024 * 1024

def path_for(url):
    root = (store.DATA / 'media').resolve()
    if not isinstance(url, str) or not url.startswith('/media/'):
        raise ValueError('Choose a saved product photo.')
    path = (root / url.removeprefix('/media/')).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('Product photo is unavailable.')
    return path

def gallery(item):
    urls = list(dict.fromkeys([item.get('image'), *item.get('photos', [])]))
    return [url for url in urls if isinstance(url, str) and url.startswith('/media/')][:12]

def candidates(item):
    urls = gallery(item)
    if item.get('source') == 'video':
        for job in store.all_rows('jobs'):
            if item['id'] in job.get('item_ids', []) or job['id'] == item.get('job_id'):
                folder = store.DATA / 'media' / job['id']
                urls += ['/media/' + p.relative_to(store.DATA / 'media').as_posix() for p in sorted(folder.glob('frame-*.jpg'))]
    # Older captures retain their job folder in the primary image URL.
    image = item.get('image', '')
    if item.get('source') == 'video' and image.startswith('/media/'):
        original = item.get('original_capture_image', image)
        try:
            folder = path_for(original).parent
            urls += ['/media/' + p.relative_to(store.DATA / 'media').as_posix() for p in sorted(folder.glob('frame-*.jpg'))]
        except ValueError:
            pass
    return list(dict.fromkeys(urls))

def add(item, raw):
    if not raw or len(raw) > LIMIT:
        raise ValueError('Choose a JPG, PNG or WebP photo up to 12 MB.')
    if len(gallery(item)) >= 12:
        raise ValueError('Keep at most 12 product photos. Remove one first.')
    try:
        with Image.open(io.BytesIO(raw)) as source:
            if source.format not in ['JPEG', 'PNG', 'WEBP']:
                raise ValueError('Choose a JPG, PNG or WebP photo.')
            if source.width * source.height > Image.MAX_IMAGE_PIXELS:
                raise ValueError('Photo must contain no more than 24 megapixels.')
            image = ImageOps.exif_transpose(source).convert('RGB')
            image.thumbnail((2400, 2400))
            return save(item, image)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValueError('This image could not be decoded. Choose a smaller JPG, PNG or WebP photo.') from None

def save(item, image):
    folder = store.DATA / 'media' / 'products' / item['id']
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (str(uuid4()) + '.jpg')
    image.save(target, format='JPEG', quality=90)
    url = '/media/' + target.relative_to(store.DATA / 'media').as_posix()
    values = gallery(item)
    item.setdefault('original_capture_image', item.get('image'))
    item.update(image=url, photos=list(dict.fromkeys([url, *values]))[:12], confirmed=False)
    return store.put('items', item)

def edit(item, data):
    url = data.get('url')
    if url not in candidates(item):
        raise ValueError('Choose a photo belonging to this product.')
    action = data.get('action')
    if action == 'remove':
        values = [u for u in gallery(item) if u != url]
        item.update(photos=values, image=values[0] if values else '/assets/product.svg', confirmed=False)
    elif action == 'primary':
        values = [url, *[u for u in gallery(item) if u != url]]
        if len(values) > 12:
            raise ValueError('Keep at most 12 product photos.')
        item.setdefault('original_capture_image', item.get('image'))
        item.update(image=url, photos=values, confirmed=False)
    elif action == 'crop':
        crop = data.get('crop')
        if not isinstance(crop, list) or len(crop) != 4 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in crop):
            raise ValueError('Crop must be four normalized coordinates.')
        x, y, w, h = crop
        if not (0 <= x < 1 and 0 <= y < 1 and .05 <= w <= 1 and .05 <= h <= 1 and x+w <= 1.001 and y+h <= 1.001):
            raise ValueError('Keep the crop inside the photo and at least 5% wide and high.')
        if len(gallery(item)) >= 12:
            raise ValueError('Remove a photo before saving a crop.')
        with Image.open(path_for(url)) as image:
            width, height = image.size
            return save(item, image.crop((int(x*width), int(y*height), min(width, int((x+w)*width)), min(height, int((y+h)*height)))).convert('RGB'))
    else:
        raise ValueError('Choose primary, crop or remove.')
    return store.put('items', item)
