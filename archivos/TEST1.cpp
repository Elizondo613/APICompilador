// Ejemplo
int factorial(int n) {
    if (n <= 1) {
        return 1;
    } else {
        int prev = factorial(n - 1);
        return n * prev;
    }
}

int main() {
    int resultado = factorial(5);
    print(resultado);
    return 0;
}