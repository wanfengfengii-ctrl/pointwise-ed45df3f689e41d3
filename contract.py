class ServiceError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code


def fail(status, code, message):
    raise ServiceError(status, code, message)


def fields(value, required, optional=()):
    if not isinstance(value, dict):
        fail(400, 'invalid_shape', 'Expected a JSON object')
    missing = set(required) - value.keys()
    extra = value.keys() - set(required) - set(optional)
    if missing or extra:
        fail(400, 'invalid_fields', f'Missing {sorted(missing)} and unexpected {sorted(extra)} fields')
    return value


def array(value, name):
    if not isinstance(value, list):
        fail(400, 'invalid_shape', f'{name} must be an array')
    return value


def text(value, name):
    if (not isinstance(value, str) or not value or value.strip() != value
            or any(ord(ch) < 32 or 0xD800 <= ord(ch) <= 0xDFFF for ch in value)):
        fail(400, 'invalid_text', f'{name} must be nonempty text without surrounding space or control characters')
    return value


def integer(value, name, minimum=1, code='invalid_integer'):
    if type(value) is not int or not minimum <= value <= 2**63 - 1:
        fail(400, code, f'{name} must be a signed 64-bit integer of at least {minimum}')
    return value
