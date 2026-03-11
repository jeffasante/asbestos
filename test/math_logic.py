import math

def is_prime(n: int) -> bool:
    """Checks if a number is prime using trial division."""
    if n <= 1:
        return False
    if n <= 3:
        return True
    if n % 2 == 0 or n % 3 == 0:
        return False
    
    i = 5
    while i * i <= n:
        if n % i == 0 or n % (i + 2) == 0:
            return False
        i += 6
    return True

def get_primes_in_range(start: int, end: int) -> list[int]:
    """Returns a list of prime numbers between start and end."""
    primes = []
    for num in range(start, end + 1):
        if is_prime(num):
            primes.append(num)
    return primes

def calculate_complex_metric(values: list[float]) -> float:
    """Calculates a custom weighted average of values."""
    if not values:
        return 0.0
    
    total = sum(v * (index + 1) for index, v in enumerate(values))
    weight_sum = sum(range(1, len(values) + 1))
    
    return total / weight_sum
