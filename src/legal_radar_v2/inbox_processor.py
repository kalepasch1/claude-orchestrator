from typing import Any, Dict


def process_inbox_item(item_data: Dict[str, Any]) -> Dict[str, Any]:
    """Process a single item from the legal inbox.

    This function expects 'item_data' to be a dictionary representing an incoming legal document or task.
    """
    result: Dict[str, Any] = {
        "status": "processed",
        "item": item_data,
    }
    return result
