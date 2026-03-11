import time

class MockService:
    def fetch_records(self, query: str):
        time.sleep(0.5)  # Simulate network latency
        if "error" in query.lower():
            raise ConnectionError("Service unavailable")
        return [{"id": 1, "data": "Sample A"}, {"id": 2, "data": "Sample B"}]

def handle_api_request(request_params: dict):
    """
    Main controller logic for a mock API request.
    Validates, calls service, handles errors.
    """
    service = MockService()
    
    # 1. Validation
    user_id = request_params.get("user_id")
    if not user_id:
        return {"code": 400, "message": "Missing user_id"}
    
    query = request_params.get("q", "")
    
    # 2. Execution with error handling
    try:
        results = service.fetch_records(query)
        
        if not results:
            return {"code": 404, "message": "No records found"}
            
        return {
            "code": 200,
            "uid": user_id,
            "count": len(results),
            "payload": results
        }
        
    except ConnectionError as ce:
        return {"code": 503, "message": str(ce)}
    except Exception as e:
        return {"code": 500, "message": f"Internal error: {str(e)}"}
