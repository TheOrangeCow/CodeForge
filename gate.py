import random


def _fizz_variant():
    n = random.randint(18, 40)
    a, b = 3, 5
    total = sum(i for i in range(1, n + 1) if i % a == 0 or i % b == 0)
    code = (
        f"total = 0\n"
        f"for i in range(1, {n} + 1):\n"
        f"    if i % {a} == 0 or i % {b} == 0:\n"
        f"        total += i\n"
        f"print(total)"
    )
    return f"What does this code print?\n\n{code}", str(total)


def _sum_squares_variant():
    n = random.randint(4, 9)
    total = sum(i * i for i in range(1, n + 1))
    return (f"Let f(n) be the sum of the squares of every integer from 1 to n. "
            f"What is f({n})?"), str(total)


def _reverse_variant():
    n = random.randint(1000, 9998)
    rev = int(str(n)[::-1])
    return (f"Take the number {n}, reverse its digits, and add the reversed "
             f"number to the original. What is the result?"), str(n + rev)


def _factorial_digits_variant():
    n = random.randint(5, 8)
    import math
    total = sum(int(d) for d in str(math.factorial(n)))
    return (f"Compute {n}! (that's {n} factorial), then add up its decimal digits. "
             f"What is the digit sum?"), str(total)


def _prime_count_variant():
    n = random.randint(20, 50)

    def is_prime(x):
        if x < 2:
            return False
        for d in range(2, int(x ** 0.5) + 1):
            if x % d == 0:
                return False
        return True

    count = sum(1 for i in range(2, n + 1) if is_prime(i))
    return (f"How many prime numbers are less than or equal to {n}?"), str(count)


VARIANTS = [_fizz_variant, _sum_squares_variant, _reverse_variant,
            _factorial_digits_variant, _prime_count_variant]


def new_gate_puzzle():
    fn = random.choice(VARIANTS)
    return fn()
