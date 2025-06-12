import os
import uuid
import shutil
import asyncio
import aiohttp
import time
from typing import Optional, Tuple, Dict, Any, List
from datetime import datetime, timedelta
from fastapi import UploadFile, HTTPException
from config.minio_service import minio_service
from PIL import Image
import math
import json
import requests
from pathlib import Path
import logging

# Configuration
# UPLOAD_DIR = "uploads/attendance_photos"
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
MAX_IMAGE_SIZE = (1920, 1080)  # Max resolution
MIN_IMAGE_SIZE = (240, 240)   # Min resolution

# Office location for geofencing
OFFICE_LOCATIONS = [
    {
        "name": "Main Office",
        "latitude": 23.834256424944652,
        "longitude": 91.28866763370992,
        "radius": 300  # meters
    }
]

# Enhanced geocoding configuration for hosted environments
GEOCODING_CONFIG = {
    "timeout": 30,  # Increased timeout for hosted environments
    "max_retries": 5,  # More retries
    "retry_delay": 2.0,  # Longer delay between retries
    "rate_limit_delay": 1.5,  # Longer rate limit delay
    "cache_duration": 3600,  # 1 hour cache (increased)
    "fallback_timeout": 15,  # Fallback service timeout
}

# Simple in-memory cache for addresses (consider using Redis in production)
address_cache = {}
last_request_time = 0

logger = logging.getLogger(__name__)

# def ensure_upload_directory():
#     """Ensure upload directory exists"""
#     Path(UPLOAD_DIR).mkdir(parents=True, exist_ok=True)

def is_allowed_file(filename: str) -> bool:
    """Check if file extension is allowed"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def generate_unique_filename(original_filename: str, employee_id: str, timestamp: datetime) -> str:
    """Generate unique filename for photo"""
    extension = original_filename.rsplit('.', 1)[1].lower()
    unique_id = str(uuid.uuid4())[:8]
    timestamp_str = timestamp.strftime("%Y%m%d_%H%M%S")
    # Changed: Add folder structure for MinIO
    return f"attendance_photos/{employee_id}_{timestamp_str}_{unique_id}.{extension}"

# COMPLETELY REPLACE validate_and_process_photo function:
async def validate_and_process_photo(
    file: UploadFile, 
    employee_id: str,
    max_size: int = MAX_FILE_SIZE
) -> Tuple[str, dict]:
    """
    Validate and process uploaded photo - Now uploads to MinIO
    Returns: (minio_url, metadata)
    """
    
    # Validate file type
    if not file.filename or not is_allowed_file(file.filename):
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        )
    
    # Check file size
    file_content = await file.read()
    if len(file_content) > max_size:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size: {max_size // (1024*1024)}MB"
        )
    
    # Reset file pointer
    await file.seek(0)
    
    try:
        # Validate image and get dimensions
        image = Image.open(file.file)
        width, height = image.size
        
        # Check minimum dimensions
        if width < MIN_IMAGE_SIZE[0] or height < MIN_IMAGE_SIZE[1]:
            raise HTTPException(
                status_code=400,
                detail=f"Image too small. Minimum size: {MIN_IMAGE_SIZE[0]}x{MIN_IMAGE_SIZE[1]}"
            )
        
        # Resize if too large
        if width > MAX_IMAGE_SIZE[0] or height > MAX_IMAGE_SIZE[1]:
            image.thumbnail(MAX_IMAGE_SIZE, Image.Resampling.LANCZOS)
            width, height = image.size
        
        # Generate unique filename with folder structure
        timestamp = datetime.now()
        object_name = generate_unique_filename(file.filename, employee_id, timestamp)
        
        # Convert processed image to bytes
        from io import BytesIO
        img_buffer = BytesIO()
        
        # Determine format based on extension
        img_format = "JPEG" if object_name.lower().endswith(('.jpg', '.jpeg')) else "PNG"
        image.save(img_buffer, format=img_format, optimize=True, quality=85)
        img_buffer.seek(0)
        
        processed_image_data = img_buffer.getvalue()
        content_type = f"image/{img_format.lower()}"
        
        # Upload to MinIO
        upload_result = await minio_service.upload_file_to_minio(
            object_name=object_name,
            file_data=processed_image_data,
            file_size=len(processed_image_data),
            content_type=content_type
        )
        
        if not upload_result["success"]:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to upload image: {upload_result['message']}"
            )
        
        # Generate metadata
        metadata = {
            "original_filename": file.filename,
            "processed_filename": object_name.split('/')[-1],  # Just the filename without path
            "object_name": object_name,  # Full path in MinIO
            "file_size": len(processed_image_data),
            "dimensions": {"width": width, "height": height},
            "upload_timestamp": timestamp.isoformat(),
            "content_type": content_type,
            "minio_url": upload_result["url"]  # Presigned URL from MinIO
        }
        
        # Return the presigned URL and metadata
        return upload_result["url"], metadata
        
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid image file: {str(e)}"
        )

def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate distance between two coordinates using Haversine formula
    Returns distance in meters
    """
    # Convert latitude and longitude from degrees to radians
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    
    # Haversine formula
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    
    # Radius of earth in meters
    r = 6371000
    
    return c * r

def validate_location(
    latitude: float, 
    longitude: float, 
    accuracy: Optional[float] = None,
    timestamp: Optional[datetime] = None
) -> dict:
    """
    Enhanced location validation with accuracy and freshness checks
    """
    # Basic coordinate validation
    if not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
        return {
            "is_valid": False,
            "message": "Invalid coordinates",
            "verification_status": "failed",
            "error_code": "INVALID_COORDINATES"
        }
    
    # Check coordinate precision (avoid obviously fake coordinates)
    if _is_coordinate_suspicious(latitude, longitude):
        return {
            "is_valid": False,
            "message": "Coordinates appear to be default/fake values",
            "verification_status": "failed",
            "error_code": "SUSPICIOUS_COORDINATES"
        }
    
    # Enhanced accuracy validation
    accuracy_result = _validate_accuracy(accuracy)
    if not accuracy_result["is_valid"]:
        return accuracy_result
    
    # Timestamp freshness check
    if timestamp:
        freshness_result = _validate_timestamp_freshness(timestamp)
        if not freshness_result["is_valid"]:
            return freshness_result
    
    # Check against office locations with dynamic radius based on accuracy
    for office in OFFICE_LOCATIONS:
        distance = calculate_distance(
            latitude, longitude,
            office["latitude"], office["longitude"]
        )
        
        # Adjust allowed radius based on GPS accuracy
        allowed_radius = office["radius"]
        if accuracy and accuracy > 20:  # If accuracy is poor, be more lenient
            allowed_radius += min(accuracy * 0.5, 100)  # Add up to 100m buffer
        
        if distance <= allowed_radius:
            return {
                "is_valid": True,
                "message": f"Location verified at {office['name']}",
                "distance_from_office": round(distance, 1),
                "office_name": office["name"],
                "verification_status": "verified",
                "accuracy_used": accuracy,
                "buffer_applied": allowed_radius - office["radius"]
            }
    
    # Find closest office for error message
    closest_office = min(
        OFFICE_LOCATIONS,
        key=lambda office: calculate_distance(
            latitude, longitude, office["latitude"], office["longitude"]
        )
    )
    
    closest_distance = calculate_distance(
        latitude, longitude,
        closest_office["latitude"], closest_office["longitude"]
    )
    
    return {
        "is_valid": False,
        "message": f"Location too far from office. Distance: {closest_distance:.0f}m from {closest_office['name']}",
        "distance_from_office": round(closest_distance, 1),
        "office_name": closest_office["name"],
        "verification_status": "failed",
        "error_code": "OUT_OF_RANGE"
    }

def _is_coordinate_suspicious(latitude: float, longitude: float) -> bool:
    """Check for obviously fake coordinates"""
    # Common fake/default coordinates
    suspicious_coords = [
        (0.0, 0.0),  # Null Island
        (37.7749, -122.4194),  # San Francisco (common default)
        (40.7128, -74.0060),   # New York (common default)
    ]
    
    for sus_lat, sus_lon in suspicious_coords:
        if abs(latitude - sus_lat) < 0.001 and abs(longitude - sus_lon) < 0.001:
            return True
    
    # Check if coordinates are too precise (might be fake)
    lat_decimals = len(str(latitude).split('.')[-1]) if '.' in str(latitude) else 0
    lon_decimals = len(str(longitude).split('.')[-1]) if '.' in str(longitude) else 0
    
    # Real GPS usually has 6-8 decimal places, more than 10 might be suspicious
    if lat_decimals > 12 or lon_decimals > 12:
        return True
    
    return False

def _validate_accuracy(accuracy: Optional[float]) -> dict:
    """Validate GPS accuracy"""
    if accuracy is None:
        return {
            "is_valid": True,
            "message": "No accuracy data provided"
        }
    
    if accuracy < 0:
        return {
            "is_valid": False,
            "message": "Invalid accuracy value",
            "verification_status": "failed",
            "error_code": "INVALID_ACCURACY"
        }
    
    if accuracy > 200:  # Very poor accuracy
        return {
            "is_valid": False,
            "message": f"Location accuracy too poor: {accuracy}m. Maximum allowed: 200m",
            "verification_status": "failed",
            "error_code": "POOR_ACCURACY"
        }
    
    return {"is_valid": True}

def _validate_timestamp_freshness(timestamp: datetime) -> dict:
    """Validate that location timestamp is recent"""
    now = datetime.now()
    age = now - timestamp
    
    # Allow up to 5 minutes old
    if age > timedelta(minutes=5):
        return {
            "is_valid": False,
            "message": f"Location data is too old: {age.total_seconds():.0f} seconds",
            "verification_status": "failed",
            "error_code": "STALE_LOCATION"
        }
    
    return {"is_valid": True}

# MAIN ENHANCED GEOCODING FUNCTION - Fixed for hosted environments
async def get_address_from_coordinates(
    latitude: float, 
    longitude: float,
    use_cache: bool = True
) -> Dict[str, Any]:
    """
    Production-ready geocoding function optimized for hosted environments
    Returns dict with address, success status, and metadata
    """
    global last_request_time
    
    # Create cache key
    cache_key = f"{latitude:.6f},{longitude:.6f}"
    
    # Check cache first
    if use_cache and cache_key in address_cache:
        cached_data = address_cache[cache_key]
        if time.time() - cached_data["timestamp"] < GEOCODING_CONFIG["cache_duration"]:
            logger.info(f"Address cache hit for {cache_key}")
            return {
                "address": cached_data["address"],
                "success": True,
                "from_cache": True,
                "service_used": cached_data.get("service", "cache"),
                "response_time_ms": 0
            }
    
    # Rate limiting
    current_time = time.time()
    if current_time - last_request_time < GEOCODING_CONFIG["rate_limit_delay"]:
        await asyncio.sleep(GEOCODING_CONFIG["rate_limit_delay"])
    
    last_request_time = time.time()
    start_time = time.time()
    
    # Define geocoding services with different approaches
    services = [
        {
            "name": "Nominatim OSM (Primary)",
            "func": _get_address_nominatim_async,
            "timeout": GEOCODING_CONFIG["timeout"]
        },
        {
            "name": "Nominatim Alternative",
            "func": _get_address_nominatim_alt_async,
            "timeout": GEOCODING_CONFIG["fallback_timeout"]
        },
        {
            "name": "OpenCage (Fallback)",
            "func": _get_address_opencage_async,
            "timeout": GEOCODING_CONFIG["fallback_timeout"]
        },
        {
            "name": "BigDataCloud (Free Tier)",
            "func": _get_address_bigdatacloud_async,
            "timeout": GEOCODING_CONFIG["fallback_timeout"]
        }
    ]
    
    last_error = None
    
    # Try each service
    for service in services:
        try:
            logger.info(f"Trying geocoding service: {service['name']}")
            
            # Use asyncio.wait_for for timeout control
            address = await asyncio.wait_for(
                service["func"](latitude, longitude),
                timeout=service["timeout"]
            )
            
            if address and len(address.strip()) > 0:
                response_time = round((time.time() - start_time) * 1000, 2)
                
                # Cache successful result
                if use_cache:
                    address_cache[cache_key] = {
                        "address": address,
                        "timestamp": time.time(),
                        "service": service["name"]
                    }
                
                logger.info(f"Successfully geocoded with {service['name']} in {response_time}ms")
                
                return {
                    "address": address,
                    "success": True,
                    "from_cache": False,
                    "service_used": service["name"],
                    "response_time_ms": response_time
                }
                
        except asyncio.TimeoutError:
            last_error = f"{service['name']} timed out after {service['timeout']}s"
            logger.warning(last_error)
        except Exception as e:
            last_error = f"{service['name']} failed: {str(e)}"
            logger.warning(last_error)
        
        # Small delay between service attempts
        await asyncio.sleep(0.5)
    
    # All services failed - return coordinates as fallback
    fallback_address = f"{latitude:.6f}, {longitude:.6f}"
    response_time = round((time.time() - start_time) * 1000, 2)
    
    logger.error(f"All geocoding services failed. Last error: {last_error}")
    
    return {
        "address": fallback_address,
        "success": False,
        "from_cache": False,
        "service_used": "fallback_coordinates",
        "response_time_ms": response_time,
        "error": last_error
    }

async def _get_address_nominatim_async(latitude: float, longitude: float) -> Optional[str]:
    """Primary Nominatim service with async HTTP client"""
    url = "https://nominatim.openstreetmap.org/reverse"
    params = {
        "lat": latitude,
        "lon": longitude,
        "format": "json",
        "addressdetails": 1,
        "zoom": 18,
        "extratags": 1
    }
    
    headers = {
        "User-Agent": "ShiftManagementApp/1.0 (https://f3d63da1.shift-automation.pages.dev)",
        "Accept": "application/json",
        "Accept-Language": "en"
    }
    
    try:
        timeout = aiohttp.ClientTimeout(total=GEOCODING_CONFIG["timeout"])
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    return _extract_readable_address(data)
                elif response.status == 429:
                    logger.warning("Nominatim rate limited")
                    await asyncio.sleep(2)
                    return None
                else:
                    logger.warning(f"Nominatim HTTP {response.status}")
                    return None
    except Exception as e:
        logger.error(f"Nominatim async error: {e}")
        return None

async def _get_address_nominatim_alt_async(latitude: float, longitude: float) -> Optional[str]:
    """Alternative Nominatim server"""
    url = "https://nominatim.org/reverse"
    params = {
        "lat": latitude,
        "lon": longitude,
        "format": "json",
        "addressdetails": 1
    }
    
    headers = {
        "User-Agent": "ShiftManagementApp/1.0",
        "Accept": "application/json"
    }
    
    try:
        timeout = aiohttp.ClientTimeout(total=GEOCODING_CONFIG["fallback_timeout"])
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    return _extract_readable_address(data)
                return None
    except Exception as e:
        logger.error(f"Nominatim alt async error: {e}")
        return None

async def _get_address_opencage_async(latitude: float, longitude: float) -> Optional[str]:
    """OpenCage Geocoding API (free tier available)"""
    # You can get a free API key from OpenCage
    api_key = os.getenv("OPENCAGE_API_KEY")
    if not api_key:
        return None
    
    url = "https://api.opencagedata.com/geocode/v1/json"
    params = {
        "q": f"{latitude},{longitude}",
        "key": api_key,
        "language": "en",
        "no_annotations": 1
    }
    
    try:
        timeout = aiohttp.ClientTimeout(total=GEOCODING_CONFIG["fallback_timeout"])
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("results"):
                        return data["results"][0].get("formatted")
                return None
    except Exception as e:
        logger.error(f"OpenCage async error: {e}")
        return None

async def _get_address_bigdatacloud_async(latitude: float, longitude: float) -> Optional[str]:
    """BigDataCloud reverse geocoding (free tier)"""
    url = "https://api.bigdatacloud.net/data/reverse-geocode-client"
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "localityLanguage": "en"
    }
    
    try:
        timeout = aiohttp.ClientTimeout(total=GEOCODING_CONFIG["fallback_timeout"])
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Build address from components
                    address_parts = []
                    if data.get("locality"):
                        address_parts.append(data["locality"])
                    if data.get("city"):
                        address_parts.append(data["city"])
                    if data.get("principalSubdivision"):
                        address_parts.append(data["principalSubdivision"])
                    if data.get("countryName"):
                        address_parts.append(data["countryName"])
                    
                    if address_parts:
                        return ", ".join(address_parts)
                return None
    except Exception as e:
        logger.error(f"BigDataCloud async error: {e}")
        return None

def _extract_readable_address(data: dict) -> Optional[str]:
    """Extract readable address from geocoding response"""
    if not data or "display_name" not in data:
        return None
    
    # Try to create a more readable address
    address_parts = []
    
    # Get address components
    address = data.get("address", {})
    
    # Building/house number and road
    if "house_number" in address and "road" in address:
        address_parts.append(f"{address['house_number']} {address['road']}")
    elif "road" in address:
        address_parts.append(address["road"])
    
    # Area/suburb
    area = (address.get("suburb") or 
            address.get("neighbourhood") or 
            address.get("hamlet") or 
            address.get("village"))
    if area:
        address_parts.append(area)
    
    # City
    city = (address.get("city") or 
            address.get("town") or 
            address.get("municipality"))
    if city:
        address_parts.append(city)
    
    # State/Province
    state = (address.get("state") or 
             address.get("province"))
    if state:
        address_parts.append(state)
    
    # Country
    if "country" in address:
        address_parts.append(address["country"])
    
    if address_parts:
        return ", ".join(address_parts)
    
    # Fallback to display_name but truncate if too long
    display_name = data["display_name"]
    if len(display_name) > 200:
        return display_name[:200] + "..."
    
    return display_name

# Backward compatibility function
async def get_address_from_coordinates_enhanced(
    latitude: float, 
    longitude: float,
    use_cache: bool = True
) -> Optional[str]:
    """
    Enhanced reverse geocoding - backward compatibility wrapper
    """
    result = await get_address_from_coordinates(latitude, longitude, use_cache)
    return result.get("address")

# def cleanup_old_photos(days_old: int = 30):
#     """
#     Clean up photos older than specified days
#     Should be run as a scheduled task
#     """
#     if not os.path.exists(UPLOAD_DIR):
#         return
    
#     cutoff_time = datetime.now().timestamp() - (days_old * 24 * 60 * 60)
    
#     for filename in os.listdir(UPLOAD_DIR):
#         file_path = os.path.join(UPLOAD_DIR, filename)
#         if os.path.isfile(file_path):
#             if os.path.getmtime(file_path) < cutoff_time:
#                 try:
#                     os.remove(file_path)
#                     print(f"Deleted old photo: {filename}")
#                 except Exception as e:
#                     print(f"Error deleting {filename}: {e}")

def get_client_ip(request) -> str:
    """Extract client IP address from request"""
    # Check for forwarded headers (if behind proxy)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip
    
    # Fallback to direct connection
    return request.client.host if request.client else "unknown"

def serialize_device_info(device_info: dict) -> str:
    """Serialize device info to JSON string for database storage"""
    try:
        return json.dumps(device_info, ensure_ascii=False)
    except:
        return ""

# Clean up old cache entries periodically
def cleanup_address_cache():
    """Remove old entries from address cache"""
    current_time = time.time()
    expired_keys = [
        key for key, data in address_cache.items()
        if current_time - data["timestamp"] > GEOCODING_CONFIG["cache_duration"]
    ]
    
    for key in expired_keys:
        del address_cache[key]
    
    logger.info(f"Cleaned up {len(expired_keys)} expired cache entries")

# Utility function to get cache statistics
def get_cache_stats() -> dict:
    """Get address cache statistics"""
    current_time = time.time()
    active_entries = sum(
        1 for data in address_cache.values()
        if current_time - data["timestamp"] < GEOCODING_CONFIG["cache_duration"]
    )
    
    return {
        "total_entries": len(address_cache),
        "active_entries": active_entries,
        "expired_entries": len(address_cache) - active_entries,
        "cache_hit_potential": active_entries / max(len(address_cache), 1) * 100
    }