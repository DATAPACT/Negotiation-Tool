# PolicyEngine

## Example policy:
```json
{
  "uid": "http://example.com/policy:001",
  "permission": [
    {
      "target": "http://example.com/asset:123",
      "action": "read",
      "constraint": {
        "leftOperand": "dateTime",
        "operator": "lt",
        "rightOperand": "2024-03-01T00:00:00Z"
      },
      "duty": [
        {
          "action": "attribute",
          "constraint": {
            "leftOperand": "dateTime",
            "operator": "lt",
            "rightOperand": "2024-01-01T00:00:00Z"
          }
        }
      ]
    }
  ],
  "prohibition": [
    {
      "target": "http://example.com/asset:123",
      "action": "write",
      "constraint": {
        "leftOperand": "dateTime",
        "operator": "gte",
        "rightOperand": "2024-01-01T00:00:00Z"
      }
    }
  ]
}
```

## Sample Requests
###  Request 1
```json
{
        "target": "http://example.com/asset:123",
        "action": "read",
        "context": {"dateTime": "2023-06-01T12:00:00Z"}
}
```
### Response 1
```json
{
    "allowed": True
}
```
### Request 2
```javascript
{
        "target": "http://example.com/asset:123",
        "action": "write",
        "context": {"dateTime": "2024-01-02T12:00:00Z"}
    }
```
### Response 2
```javascript
{
        "allowed": False, 
        "reason": "Prohibition applies"
}
```
### Request 3
```javascript
{
        "target": "http://example.com/asset:123",
        "action": "read",
        "context": {"dateTime": "2024-02-01T12:00:00Z"}  # After the duty's constraint date
}
```
### Response 3
```javascript
{
        "allowed": False, 
        "reason": "Duty not met"
}
```
### Request 4
```javascript
{
        "target": "http://example.com/asset:123",
        "action": "read",
        "context": {"dateTime": "2024-03-02T12:00:00Z"}  # After the permission's constraint date
}
```
### Response 4
```javascript
{
        "allowed": False, 
        "reason": "Constraint not satisfied for permission"
}
```
### Request 5
```javascript
{
        "target": "http://example.com/asset:999",  # Non-existing target
        "action": "read",
        "context": {"dateTime": "2023-06-01T12:00:00Z"
        }
    }
```
### Response 5
```javascript
{
        "allowed": False, 
        "reason": "No applicable permission found"
}
```


