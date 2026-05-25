import re
import json
import os
import time
import uuid
import shutil
import subprocess
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI(title="Compilador API", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ─────────────────────────────────────────────────────────────
# LÉXICO
# ─────────────────────────────────────────────────────────────
token_patron = {
    "COMMENT_LINE":  r'//[^\n]*',
    "COMMENT_BLOCK": r'/\*[\s\S]*?\*/',
    "STRING":        r'"[^"]*"',
    "KEYWORDS":      r'\b(if|else|while|for|return|int|float|void|char|bool|then|print|printf|true|false)\b',
    "IDENTIFIER":    r'\b[a-zA-Z_][a-zA-Z0-9_]*\b',
    "NUMBER":        r'\b\d+(\.\d+)?\b',
    "OPERATORS":     r'\+\+|--|==|!=|<=|>=|&&|\|\||[+\-*/=<>!]',
    "DELIMITERS":    r'[\[\](),;{}]',
    "WHITESPACE":    r'\s+',
}

def identificar_tokens(texto):
    patron = '|'.join(f'(?P<{t}>{p})' for t, p in token_patron.items())
    result = []
    for m in re.compile(patron).finditer(texto):
        for tok, val in m.groupdict().items():
            if val and tok not in ("WHITESPACE", "COMMENT_LINE", "COMMENT_BLOCK"):
                result.append((tok, val))
    return result

# ─────────────────────────────────────────────────────────────
# NODOS AST
# ─────────────────────────────────────────────────────────────
class NodoAST:
    def traducirPy(self):   raise NotImplementedError(f"{type(self).__name__}.traducirPy()")
    def traducirJava(self):  raise NotImplementedError(f"{type(self).__name__}.traducirJava()")
    def traducirC(self):     raise NotImplementedError(f"{type(self).__name__}.traducirC()")
    def generarCodigo(self): raise NotImplementedError(f"{type(self).__name__}.generarCodigo()")
    def optimizar(self):     return self

class NodoPrograma(NodoAST):
    def __init__(self, globales, funciones, main):
        self.globales = globales
        self.funciones = funciones
        self.main = main

    def traducirPy(self):
        partes = [g.traducirPy() for g in self.globales]
        partes.extend([f.traducirPy() for f in self.funciones])
        if self.main: partes.append(self.main.traducirPy())
        return "\n\n".join(partes).strip()

    def traducirJava(self):
        partes = ["    static " + g.traducirJava() for g in self.globales]
        partes.extend([f.traducirJava() for f in self.funciones])
        if self.main: partes.append(self.main.traducirJava())
        return "public class Programa {\n" + "\n\n".join(partes) + "\n}"

    def traducirC(self):
        partes = [g.traducirC() for g in self.globales]
        partes.extend([f.traducirC() for f in self.funciones])
        if self.main: partes.append(self.main.traducirC())
        return "#include <stdio.h>\n\n" + "\n\n".join(partes).strip()
        
    def generarCodigo(self):
        partes = [g.generarCodigo() for g in self.globales]
        partes.extend([f.generarCodigo() for f in self.funciones])
        if self.main: partes.append(self.main.generarCodigo())
        return "\n\n".join(partes).strip()

    def optimizar(self):
        return NodoPrograma(
            [g.optimizar() for g in self.globales],
            [f.optimizar() for f in self.funciones],
            self.main.optimizar() if self.main else None
        )

class NodoFuncion(NodoAST):
    def __init__(self, tipo_retorno, nombre, parametros, cuerpo):
        self.tipo_retorno = tipo_retorno
        self.nombre = nombre
        self.parametros = parametros
        self.cuerpo = cuerpo

    def traducirPy(self):
        params = ', '.join(p.traducirPy() for p in self.parametros)
        cuerpo = "\n    ".join(c.traducirPy() for c in self.cuerpo) or "pass"
        return f"def {self.nombre[1]}({params}):\n    {cuerpo}"

    def traducirJava(self):
        params = ', '.join(p.traducirJava() for p in self.parametros)
        cuerpo = "\n        ".join(c.traducirJava() for c in self.cuerpo)
        if self.nombre[1] == 'main':
            return f"    public static void main(String[] args) {{\n        {cuerpo}\n    }}"
        return f"    public static {self.tipo_retorno[1]} {self.nombre[1]}({params}) {{\n        {cuerpo}\n    }}"

    def traducirC(self):
        params = ', '.join(p.traducirC() for p in self.parametros)
        cuerpo = "\n    ".join(c.traducirC() for c in self.cuerpo)
        if self.nombre[1] == 'main':
            return f"int main() {{\n    {cuerpo}\n    return 0;\n}}"
        tipo = "int" if self.tipo_retorno[1] == "bool" else self.tipo_retorno[1]
        return f"{tipo} {self.nombre[1]}({params}) {{\n    {cuerpo}\n}}"

    def generarCodigo(self):
        cuerpo = "\n    ".join(c.generarCodigo() for c in self.cuerpo)
        ps = ', '.join(p.nombre[1] for p in self.parametros)
        return f"; === {self.nombre[1]}({ps}) -> {self.tipo_retorno[1]} ===\n{self.nombre[1]}:\n    {cuerpo}"

    def optimizar(self):
        return NodoFuncion(self.tipo_retorno, self.nombre,
                           self.parametros, [c.optimizar() for c in self.cuerpo])
    def traducirC(self):
        params = ', '.join(p.traducirC() for p in self.parametros)
        cuerpo = "\n    ".join(c.traducirC() for c in self.cuerpo)
        if self.nombre[1] == 'main':
            return f"int main() {{\n    {cuerpo}\n    system(\"pause\");\n    return 0;\n}}"
        return f"{self.tipo_retorno[1]} {self.nombre[1]}({params}) {{\n    {cuerpo}\n}}"

class NodoParametro(NodoAST):
    def __init__(self, nombre, tipo, es_array=False):
        self.nombre = nombre; self.tipo = tipo; self.es_array = es_array

    def traducirPy(self): return self.nombre[1]
    def traducirJava(self): return f"{self.tipo[1]}{'[]' if self.es_array else ''} {self.nombre[1]}"
    def traducirC(self): return f"{self.tipo[1]} {'*' if self.es_array else ''}{self.nombre[1]}"
    def generarCodigo(self): return f"; param {self.tipo[1]} {self.nombre[1]}"
    def traducirC(self): return f"{self.tipo[1]}{'[]' if self.es_array else ''} {self.nombre[1]}"

class NodoAsignacion(NodoAST):
    def __init__(self, tipo, nombre, expresion, es_declaracion=True):
        self.tipo = tipo; self.nombre = nombre
        self.expresion = expresion; self.es_declaracion = es_declaracion

    def traducirPy(self):
        return f"{self.nombre[1]} = {self.expresion.traducirPy()}"

    def traducirJava(self):
        expr = self.expresion.traducirJava()
        if self.es_declaracion and self.tipo:
            return f"{self.tipo[1]} {self.nombre[1]} = {expr};"
        return f"{self.nombre[1]} = {expr};"

    def traducirC(self):
        expr = self.expresion.traducirC()
        if self.es_declaracion and self.tipo:
            tipo = self.tipo[1]
            if tipo == "bool":
                tipo = "int"
            return f"{tipo} {self.nombre[1]} = {expr};"
        return f"{self.nombre[1]} = {expr};"

    def generarCodigo(self):
        return f"MOV {self.nombre[1]}, {self.expresion.generarCodigo()}"

    def optimizar(self):
        return NodoAsignacion(self.tipo, self.nombre, self.expresion.optimizar(), self.es_declaracion)
    def traducirC(self):
        expr = self.expresion.traducirC()
        if self.es_declaracion and self.tipo:
            return f"{self.tipo[1]} {self.nombre[1]} = {expr};"
        return f"{self.nombre[1]} = {expr};"

class NodoDeclaracionArray(NodoAST):
    def __init__(self, tipo, nombre, tamanio, valores=None):
        self.tipo = tipo; self.nombre = nombre
        self.tamanio = tamanio; self.valores = valores or []

    def traducirPy(self):
        if self.valores:
            return f"{self.nombre[1]} = [{', '.join(v.traducirPy() for v in self.valores)}]"
        return f"{self.nombre[1]} = [0] * {self.tamanio}"

    def traducirJava(self):
        if self.valores:
            vals = ', '.join(v.traducirJava() for v in self.valores)
            return f"{self.tipo[1]}[] {self.nombre[1]} = {{{vals}}};"
        return f"{self.tipo[1]}[] {self.nombre[1]} = new {self.tipo[1]}[{self.tamanio}];"

    def traducirC(self):
        if self.valores:
            vals = ', '.join(v.traducirC() for v in self.valores)
            return f"{self.tipo[1]} {self.nombre[1]}[] = {{{vals}}};"
        return f"{self.tipo[1]} {self.nombre[1]}[{self.tamanio}];"

    def generarCodigo(self):
        return f"ALLOC {self.nombre[1]}, {self.tamanio} ; {self.tipo[1]}[]"
    def traducirC(self):
        if self.valores:
            vals = ', '.join(v.traducirC() for v in self.valores)
            return f"{self.tipo[1]} {self.nombre[1]}[{self.tamanio}] = {{{vals}}};"
        return f"{self.tipo[1]} {self.nombre[1]}[{self.tamanio}];"

class NodoAsignacionArray(NodoAST):
    def __init__(self, nombre, indice, expresion):
        self.nombre = nombre; self.indice = indice; self.expresion = expresion

    def traducirPy(self):
        return f"{self.nombre[1]}[{self.indice.traducirPy()}] = {self.expresion.traducirPy()}"

    def traducirJava(self):
        return f"{self.nombre[1]}[{self.indice.traducirJava()}] = {self.expresion.traducirJava()};"

    def traducirC(self):
        return f"{self.nombre[1]}[{self.indice.traducirC()}] = {self.expresion.traducirC()};"

    def generarCodigo(self):
        return f"MOV {self.nombre[1]}[{self.indice.generarCodigo()}], {self.expresion.generarCodigo()}"
    def traducirC(self):
        return f"{self.nombre[1]}[{self.indice.traducirC()}] = {self.expresion.traducirC()};"
    def optimizar(self):
        return NodoAsignacionArray(self.nombre, self.indice.optimizar(), self.expresion.optimizar())

class NodoAccesoArray(NodoAST):
    def __init__(self, nombre, indice):
        self.nombre = nombre; self.indice = indice

    def traducirPy(self): return f"{self.nombre[1]}[{self.indice.traducirPy()}]"
    def traducirJava(self): return f"{self.nombre[1]}[{self.indice.traducirJava()}]"
    def traducirC(self): return f"{self.nombre[1]}[{self.indice.traducirC()}]"
    def generarCodigo(self): return f"LOAD {self.nombre[1]}[{self.indice.generarCodigo()}]"
    def traducirC(self): return f"{self.nombre[1]}[{self.indice.traducirC()}]"
    def optimizar(self): return NodoAccesoArray(self.nombre, self.indice.optimizar())

class NodoOperacion(NodoAST):
    _ASM = {'+':'ADD','-':'SUB','*':'MUL','/':'DIV','==':'CMP_EQ','!=':'CMP_NEQ',
            '<':'CMP_LT','>':'CMP_GT','<=':'CMP_LE','>=':'CMP_GE','&&':'AND','||':'OR'}
    _PY  = {'&&':'and','||':'or'}

    def __init__(self, izquierda, operador, derecha):
        self.izquierda = izquierda; self.operador = operador; self.derecha = derecha

    def traducirPy(self):
        op = self._PY.get(self.operador[1], self.operador[1])
        return f"({self.izquierda.traducirPy()} {op} {self.derecha.traducirPy()})"

    def traducirJava(self):
        return f"({self.izquierda.traducirJava()} {self.operador[1]} {self.derecha.traducirJava()})"

    def traducirC(self):
        return f"({self.izquierda.traducirC()} {self.operador[1]} {self.derecha.traducirC()})"

    def generarCodigo(self):
        op = self._ASM.get(self.operador[1], self.operador[1])
        return f"{op} {self.izquierda.generarCodigo()}, {self.derecha.generarCodigo()}"
    def traducirC(self):
        return f"({self.izquierda.traducirC()} {self.operador[1]} {self.derecha.traducirC()})"
    def optimizar(self):
        izq = self.izquierda.optimizar()
        der = self.derecha.optimizar()
        if isinstance(izq, (NodoNumero, NodoFloat)) and isinstance(der, (NodoNumero, NodoFloat)):
            op = self.operador[1]
            vi, vd = float(izq.valor[1]), float(der.valor[1])
            ops = {'+': vi+vd, '-': vi-vd, '*': vi*vd}
            if op == '/' and vd != 0: ops['/'] = vi / vd
            if op in ops:
                r = ops[op]
                return NodoNumero(('NUMBER', str(int(r)) if r == int(r) else str(r)))
        return NodoOperacion(izq, self.operador, der)

class NodoNegacion(NodoAST):
    def __init__(self, expresion): self.expresion = expresion

    def traducirPy(self): return f"not ({self.expresion.traducirPy()})"
    def traducirJava(self): return f"!({self.expresion.traducirJava()})"
    def traducirC(self): return f"!({self.expresion.traducirC()})"
    def generarCodigo(self): return f"NOT {self.expresion.generarCodigo()}"
    def traducirC(self): return f"!({self.expresion.traducirC()})"
    def optimizar(self): return NodoNegacion(self.expresion.optimizar())

class NodoIf(NodoAST):
    def __init__(self, condicion, cuerpo_if, cuerpo_else=None):
        self.condicion = condicion; self.cuerpo_if = cuerpo_if; self.cuerpo_else = cuerpo_else

    def traducirPy(self):
        cuerpo = "\n    ".join(c.traducirPy() for c in self.cuerpo_if) or "pass"
        r = f"if {self.condicion.traducirPy()}:\n    {cuerpo}"
        if self.cuerpo_else:
            eb = "\n    ".join(c.traducirPy() for c in self.cuerpo_else) or "pass"
            r += f"\nelse:\n    {eb}"
        return r

    def traducirJava(self):
        cuerpo = "\n        ".join(c.traducirJava() for c in self.cuerpo_if)
        r = f"if ({self.condicion.traducirJava()}) {{\n        {cuerpo}\n    }}"
        if self.cuerpo_else:
            eb = "\n        ".join(c.traducirJava() for c in self.cuerpo_else)
            r += f" else {{\n        {eb}\n    }}"
        return r

    def traducirC(self):
        cuerpo = "\n    ".join(c.traducirC() for c in self.cuerpo_if)
        r = f"if ({self.condicion.traducirC()}) {{\n    {cuerpo}\n}}"
        if self.cuerpo_else:
            eb = "\n    ".join(c.traducirC() for c in self.cuerpo_else)
            r += f" else {{\n    {eb}\n}}"
        return r

    def generarCodigo(self):
        uid = abs(id(self)) % 100000
        le, lend = f"else_{uid}", f"endif_{uid}"
        cuerpo = "\n    ".join(c.generarCodigo() for c in self.cuerpo_if)
        r = f"CMP {self.condicion.generarCodigo()}\n    JZ {le}\n    {cuerpo}\n    JMP {lend}\n{le}:"
        if self.cuerpo_else:
            eb = "\n    ".join(c.generarCodigo() for c in self.cuerpo_else)
            r += f"\n    {eb}"
        return r + f"\n{lend}:"
    def traducirC(self):
        cuerpo = "\n    ".join(c.traducirC() for c in self.cuerpo_if) or "    // TODO: cuerpo if"
        r = f"if ({self.condicion.traducirC()}) {{\n{cuerpo}\n}}"
        if self.cuerpo_else:
            eb = "\n    ".join(c.traducirC() for c in self.cuerpo_else) or "    // TODO: cuerpo else"
            r += f" else {{\n{eb}\n}}"
        return r
    def optimizar(self):
        return NodoIf(self.condicion.optimizar(),
                      [c.optimizar() for c in self.cuerpo_if],
                      [c.optimizar() for c in self.cuerpo_else] if self.cuerpo_else else None)

class NodoWhile(NodoAST):
    def __init__(self, condicion, cuerpo):
        self.condicion = condicion; self.cuerpo = cuerpo

    def traducirPy(self):
        cuerpo = "\n    ".join(c.traducirPy() for c in self.cuerpo) or "pass"
        return f"while {self.condicion.traducirPy()}:\n    {cuerpo}"

    def traducirJava(self):
        cuerpo = "\n        ".join(c.traducirJava() for c in self.cuerpo)
        return f"while ({self.condicion.traducirJava()}) {{\n        {cuerpo}\n    }}"

    def traducirC(self):
        cuerpo = "\n    ".join(c.traducirC() for c in self.cuerpo)
        return f"while ({self.condicion.traducirC()}) {{\n    {cuerpo}\n}}"

    def generarCodigo(self):
        uid = abs(id(self)) % 100000
        ls, le = f"while_{uid}", f"endwhile_{uid}"
        cuerpo = "\n    ".join(c.generarCodigo() for c in self.cuerpo)
        return f"{ls}:\n    CMP {self.condicion.generarCodigo()}\n    JZ {le}\n    {cuerpo}\n    JMP {ls}\n{le}:"
    def traducirC(self):
        cuerpo = "\n    ".join(c.traducirC() for c in self.cuerpo) or "    // TODO: cuerpo while"
        return f"while ({self.condicion.traducirC()}) {{\n{cuerpo}\n}}"
    def optimizar(self):
        return NodoWhile(self.condicion.optimizar(), [c.optimizar() for c in self.cuerpo])

class NodoFor(NodoAST):
    def __init__(self, init, condicion, incremento, cuerpo):
        self.init = init; self.condicion = condicion
        self.incremento = incremento; self.cuerpo = cuerpo

    def traducirPy(self):
        init  = self.init.traducirPy() if self.init else ""
        cond  = self.condicion.traducirPy() if self.condicion else "True"
        inc   = self.incremento.traducirPy() if self.incremento else ""
        cuerpo = "\n    ".join(c.traducirPy() for c in self.cuerpo) or "pass"
        return f"{init}\nwhile {cond}:\n    {cuerpo}\n    {inc}"

    def traducirJava(self):
        init  = (self.init.traducirJava().rstrip(";") if self.init else "")
        cond  = self.condicion.traducirJava() if self.condicion else "true"
        inc   = (self.incremento.traducirJava().rstrip(";") if self.incremento else "")
        cuerpo = "\n        ".join(c.traducirJava() for c in self.cuerpo)
        return f"for ({init}; {cond}; {inc}) {{\n        {cuerpo}\n    }}"

    def traducirC(self):
        init  = (self.init.traducirC().rstrip(";") if self.init else "")
        cond  = self.condicion.traducirC() if self.condicion else "1"
        inc   = (self.incremento.traducirC().rstrip(";") if self.incremento else "")
        cuerpo = "\n    ".join(c.traducirC() for c in self.cuerpo)
        return f"for ({init}; {cond}; {inc}) {{\n    {cuerpo}\n}}"

    def generarCodigo(self):
        uid = abs(id(self)) % 100000
        ls, le = f"for_{uid}", f"endfor_{uid}"
        init  = self.init.generarCodigo() if self.init else ""
        cond  = self.condicion.generarCodigo() if self.condicion else "1"
        inc   = self.incremento.generarCodigo() if self.incremento else ""
        cuerpo = "\n    ".join(c.generarCodigo() for c in self.cuerpo)
        return f"{init}\n{ls}:\n    CMP {cond}\n    JZ {le}\n    {cuerpo}\n    {inc}\n    JMP {ls}\n{le}:"
    def traducirC(self):
        init  = self.init.traducirC().rstrip(";") if self.init else ""
        cond  = self.condicion.traducirC() if self.condicion else "true"
        inc   = self.incremento.traducirC().rstrip(";") if self.incremento else ""
        cuerpo = "\n    ".join(c.traducirC() for c in self.cuerpo) or "    // TODO: cuerpo for"
        return f"for ({init}; {cond}; {inc}) {{\n{cuerpo}\n}}"
    def optimizar(self):
        return NodoFor(
            self.init.optimizar() if self.init else None,
            self.condicion.optimizar() if self.condicion else None,
            self.incremento.optimizar() if self.incremento else None,
            [c.optimizar() for c in self.cuerpo])

class NodoRetorno(NodoAST):
    def __init__(self, expresion): self.expresion = expresion

    def traducirPy(self):
        return f"return {self.expresion.traducirPy()}" if self.expresion else "return"

    def traducirJava(self):
        return f"return {self.expresion.traducirJava()};" if self.expresion else "return;"

    def traducirC(self):
        return f"return {self.expresion.traducirC()};" if self.expresion else "return;"

    def generarCodigo(self):
        return f"MOV eax, {self.expresion.generarCodigo()}\n    RET" if self.expresion else "RET"
    def traducirC(self):
        return f"return {self.expresion.traducirC()};" if self.expresion else "return;"
    def optimizar(self):
        return NodoRetorno(self.expresion.optimizar() if self.expresion else None)

class NodoIdentificador(NodoAST):
    def __init__(self, nombre): self.nombre = nombre

    def traducirPy(self): return self.nombre[1]
    def traducirJava(self): return self.nombre[1]
    def traducirC(self): return self.nombre[1]
    def generarCodigo(self): return self.nombre[1]
    def traducirC(self): return self.nombre[1]

class NodoNumero(NodoAST):
    def __init__(self, valor): self.valor = valor

    def traducirPy(self): return str(self.valor[1])
    def traducirJava(self): return str(self.valor[1])
    def traducirC(self): return str(self.valor[1])
    def generarCodigo(self): return str(self.valor[1])
    def traducirC(self): return str(self.valor[1])

class NodoFloat(NodoAST):
    def __init__(self, valor): self.valor = valor

    def traducirPy(self): return str(self.valor[1])
    def traducirJava(self): return f"{self.valor[1]}f"
    def traducirC(self): return f"{self.valor[1]}f"
    def generarCodigo(self): return str(self.valor[1])
    def traducirC(self): return str(self.valor[1])

class NodoString(NodoAST):
    def __init__(self, valor): self.valor = valor

    def traducirPy(self): return self.valor[1]
    def traducirJava(self): return self.valor[1]
    def traducirC(self): return self.valor[1]
    def generarCodigo(self): return f'DB {self.valor[1]}, 0'
    def traducirC(self): return self.valor[1]

class NodoBoolean(NodoAST):
    def __init__(self, valor): self.valor = valor

    def traducirPy(self): return "True" if self.valor[1] == "true" else "False"
    def traducirJava(self): return self.valor[1]
    def traducirC(self): return "1" if self.valor[1] == "true" else "0"
    def generarCodigo(self): return "1" if self.valor[1] == "true" else "0"
    def traducirC(self): return self.valor[1]

class NodoLlamadaFuncion(NodoAST):
    def __init__(self, nombre_funcion, argumentos):
        self.nombre_funcion = nombre_funcion; self.argumentos = argumentos

    def traducirPy(self):
        return f"{self.nombre_funcion}({', '.join(a.traducirPy() for a in self.argumentos)})"

    def traducirJava(self):
        return f"{self.nombre_funcion}({', '.join(a.traducirJava() for a in self.argumentos)})"

    def traducirC(self):
        return f"{self.nombre_funcion}({', '.join(a.traducirC() for a in self.argumentos)})"

    def generarCodigo(self):
        args = ', '.join(a.generarCodigo() for a in self.argumentos)
        return f"CALL {self.nombre_funcion} ; args=({args})"
    def traducirC(self):
        return f"{self.nombre_funcion}({', '.join(a.traducirC() for a in self.argumentos)})"

class NodoPrint(NodoAST):
    def __init__(self, expresion): self.expresion = expresion

    def traducirPy(self): return f"print({self.expresion.traducirPy()})"
    def traducirJava(self): return f"System.out.println({self.expresion.traducirJava()});"
    def traducirC(self): return f'printf("%d\\n", {self.expresion.traducirC()});'
    def generarCodigo(self): return f"PRINT {self.expresion.generarCodigo()}"
    def traducirC(self): return f'printf("%d", {self.expresion.traducirC()});'
    def optimizar(self): return NodoPrint(self.expresion.optimizar())

class NodoPrintf(NodoAST):
    def __init__(self, expresion): self.expresion = expresion

    def traducirPy(self): return f"print({self.expresion.traducirPy()})"
    def traducirJava(self): return f"System.out.printf({self.expresion.traducirJava()});"
    def traducirC(self): return f"printf({self.expresion.traducirC()});"
    def generarCodigo(self): return f"PRINTF {self.expresion.generarCodigo()}"
    def traducirC(self): return f'printf({self.expresion.traducirC()});'
    def optimizar(self): return NodoPrintf(self.expresion.optimizar())

class NodoIncrementoDecremento(NodoAST):
    def __init__(self, nombre, operador):
        self.nombre = nombre; self.operador = operador

    def traducirPy(self):
        return f"{self.nombre[1]} += 1" if self.operador == "++" else f"{self.nombre[1]} -= 1"

    def traducirJava(self): return f"{self.nombre[1]}{self.operador};"
    def traducirC(self): return f"{self.nombre[1]}{self.operador};"
    def generarCodigo(self):
        return f"INC {self.nombre[1]}" if self.operador == "++" else f"DEC {self.nombre[1]}"
    def traducirC(self):
        return f"{self.nombre[1]}{self.operador};"

# ─────────────────────────────────────────────────────────────
# TABLA DE SÍMBOLOS (con ámbitos)
# ─────────────────────────────────────────────────────────────
class TablaSimbolos:
    def __init__(self):
        self.simbolos = {}
        self.ambitos = [{}]

    def entrar_ambito(self): self.ambitos.append({})
    def salir_ambito(self): self.ambitos.pop()

    def agregar(self, nombre, tipo, valor=None, es_array=False):
        if nombre in self.ambitos[-1]:
            raise Exception(f"Error semántico: '{nombre}' ya declarado en este ámbito")
        self.ambitos[-1][nombre] = {'tipo': tipo, 'valor': valor, 'es_array': es_array}
        self.simbolos[nombre] = self.ambitos[-1][nombre]

    def buscar(self, nombre):
        for ambito in reversed(self.ambitos):
            if nombre in ambito: return ambito[nombre]
        raise Exception(f"Error semántico: '{nombre}' no fue declarado")

    def actualizar(self, nombre, valor):
        for ambito in reversed(self.ambitos):
            if nombre in ambito:
                ambito[nombre]['valor'] = valor
                self.simbolos[nombre]['valor'] = valor
                return
        raise Exception(f"Error semántico: '{nombre}' no existe")

    def serializar(self): return self.simbolos

# ─────────────────────────────────────────────────────────────
# SISTEMA DE TIPOS
# ─────────────────────────────────────────────────────────────
class SistemaTipos:
    @staticmethod
    def es_compatible(t1, t2):
        if t1 == t2: return True
        if 'float' in (t1, t2) and 'int' in (t1, t2): return True
        return False

    @staticmethod
    def tipo_resultante(t1, t2, operador):
        if t1 == 'float' or t2 == 'float':
            return 'float'
        return 'int'


# ─────────────────────────────────────────────────────────────
# ANALIZADOR SEMÁNTICO
# ─────────────────────────────────────────────────────────────
class AnalizadorSemantico:
    def __init__(self):
        self.tabla = TablaSimbolos()
        self.funciones = {}
        self.pasos = []

    def log(self, m): self.pasos.append(m)

    def analizar(self, nodo):
        if nodo is None: return

        if isinstance(nodo, NodoPrograma):
            self.log("Analizando programa...")
            for g in nodo.globales: self.analizar(g)
            for f in nodo.funciones: self.analizar(f)
            if nodo.main: self.analizar(nodo.main)

        elif isinstance(nodo, NodoFuncion):
            self.log(f"Función: {nodo.nombre[1]}() -> {nodo.tipo_retorno[1]}")
            self.funciones[nodo.nombre[1]] = {
                'params': [(p.nombre[1], p.tipo[1]) for p in nodo.parametros],
                'tipo_retorno': nodo.tipo_retorno[1]
            }
            self.tabla.entrar_ambito()
            for p in nodo.parametros:
                self.tabla.agregar(p.nombre[1], p.tipo[1])
            for inst in nodo.cuerpo: self.analizar(inst)
            self.tabla.salir_ambito()

        elif isinstance(nodo, NodoAsignacion):
            self.analizar(nodo.expresion)
            if nodo.es_declaracion:
                tipo = nodo.tipo[1] if nodo.tipo else 'int'
                self.tabla.agregar(nodo.nombre[1], tipo)
                self.log(f"     var: {tipo} {nodo.nombre[1]}")
            else:
                self.tabla.buscar(nodo.nombre[1])

        elif isinstance(nodo, NodoDeclaracionArray):
            self.tabla.agregar(nodo.nombre[1], nodo.tipo[1], es_array=True)
            self.log(f"     array: {nodo.tipo[1]} {nodo.nombre[1]}[{nodo.tamanio}]")

        elif isinstance(nodo, NodoAsignacionArray):
            self.tabla.buscar(nodo.nombre[1])
            self.analizar(nodo.indice); self.analizar(nodo.expresion)

        elif isinstance(nodo, NodoOperacion):
            if nodo.operador[1] == '/' and isinstance(nodo.derecha, NodoNumero):
                if float(nodo.derecha.valor[1]) == 0:
                    raise Exception("Error semántico: división entre cero")
            self.analizar(nodo.izquierda); self.analizar(nodo.derecha)

        elif isinstance(nodo, NodoIdentificador):
            self.tabla.buscar(nodo.nombre[1])

        elif isinstance(nodo, (NodoIf, NodoWhile)):
            self.analizar(nodo.condicion)
            self.tabla.entrar_ambito()
            for inst in nodo.cuerpo_if if isinstance(nodo, NodoIf) else nodo.cuerpo:
                self.analizar(inst)
            self.tabla.salir_ambito()
            if isinstance(nodo, NodoIf) and nodo.cuerpo_else:
                self.tabla.entrar_ambito()
                for inst in nodo.cuerpo_else: self.analizar(inst)
                self.tabla.salir_ambito()

        elif isinstance(nodo, NodoFor):
            self.tabla.entrar_ambito()
            if nodo.init: self.analizar(nodo.init)
            if nodo.condicion: self.analizar(nodo.condicion)
            if nodo.incremento: self.analizar(nodo.incremento)
            for inst in nodo.cuerpo: self.analizar(inst)
            self.tabla.salir_ambito()

        elif isinstance(nodo, NodoRetorno):
            if nodo.expresion: self.analizar(nodo.expresion)

        elif isinstance(nodo, (NodoPrint, NodoPrintf, NodoNegacion)):
            self.analizar(nodo.expresion)

        elif isinstance(nodo, NodoLlamadaFuncion):
            if nodo.nombre_funcion not in self.funciones:
                raise Exception(f"Error semántico: función '{nodo.nombre_funcion}' no declarada")
            esperados = len(self.funciones[nodo.nombre_funcion]['params'])
            recibidos = len(nodo.argumentos)
            if esperados != recibidos:
                raise Exception(
                    f"'{nodo.nombre_funcion}' espera {esperados} args, recibió {recibidos}")
            self.log(f"     llamada OK: {nodo.nombre_funcion}()")
            for a in nodo.argumentos: self.analizar(a)

        elif isinstance(nodo, NodoIncrementoDecremento):
            self.tabla.buscar(nodo.nombre[1])

# ─────────────────────────────────────────────────────────────
# PARSER
# ─────────────────────────────────────────────────────────────
class Parser:
    def __init__(self, tokens):
        self.tokens = tokens; self.pos = 0

    def actual(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def coincidir(self, tipo):
        t = self.actual()
        if t and t[0] == tipo:
            self.pos += 1; return t
        raise SyntaxError(f"Se esperaba tipo '{tipo}' pero se encontró: {t}")

    def coincidir_valor(self, valor):
        t = self.actual()
        if t and t[1] == valor:
            self.pos += 1; return t
        raise SyntaxError(f"Se esperaba '{valor}' pero se encontró: {t}")

    def parse(self): return self.programa()

    def programa(self):
        funciones = []
        globales = []
        while self.actual() and self.actual()[1] != 'main':
            if self.pos + 2 < len(self.tokens) and self.tokens[self.pos + 2][1] == '(':
                funciones.append(self.funcion())
            else:
                globales.append(self.declaracion())
        main = self.funcion() if self.actual() and self.actual()[1] == 'main' else None
        return NodoPrograma(globales, funciones, main)

    def funcion(self):
        tipo = self.coincidir("KEYWORDS")
        nombre = self.coincidir("IDENTIFIER")
        self.coincidir_valor("(")
        params = [] if nombre[1] == 'main' else self.parametros()
        self.coincidir_valor(")")
        self.coincidir_valor("{")
        cuerpo = self.cuerpo()
        self.coincidir_valor("}")
        return NodoFuncion(tipo, nombre, params, cuerpo)

    def parametros(self):
        lista = []
        if self.actual() and self.actual()[1] == ')': return lista
        tipo = self.coincidir("KEYWORDS")
        nombre = self.coincidir("IDENTIFIER")
        es_array = False
        if self.actual() and self.actual()[1] == '[':
            self.coincidir_valor("["); self.coincidir_valor("]"); es_array = True
        lista.append(NodoParametro(nombre, tipo, es_array))
        while self.actual() and self.actual()[1] == ',':
            self.coincidir_valor(",")
            tipo = self.coincidir("KEYWORDS")
            nombre = self.coincidir("IDENTIFIER")
            es_array = False
            if self.actual() and self.actual()[1] == '[':
                self.coincidir_valor("["); self.coincidir_valor("]"); es_array = True
            lista.append(NodoParametro(nombre, tipo, es_array))
        return lista

    def cuerpo(self):
        instrucciones = []
        while self.actual() and self.actual()[1] != '}':
            instrucciones.append(self.instruccion())
        return instrucciones

    def instruccion(self):
        t = self.actual()
        if t is None: raise SyntaxError("Fin de archivo inesperado")
        v = t[1]
        if v == 'return': return self.sentencia_return()
        if v == 'if':     return self.sentencia_if()
        if v == 'while':  return self.sentencia_while()
        if v == 'for':    return self.sentencia_for()
        if v == 'print':  return self.sentencia_print()
        if v == 'printf': return self.sentencia_printf()
        if t[0] == 'KEYWORDS' and v in ('int','float','void','char','bool'):
            return self.declaracion()
        if t[0] == 'IDENTIFIER':
            return self.instruccion_identificador()
        raise SyntaxError(f"Instrucción no reconocida: {t}")

    def declaracion(self):
        tipo = self.coincidir("KEYWORDS")
        nombre = self.coincidir("IDENTIFIER")
        if self.actual() and self.actual()[1] == '[':
            self.coincidir_valor("[")
            if self.actual() and self.actual()[1] == ']':
                self.coincidir_valor("]")
                self.coincidir_valor("=")
                self.coincidir_valor("{")
                valores = self.lista_valores()
                self.coincidir_valor("}")
                self.coincidir_valor(";")
                return NodoDeclaracionArray(tipo, nombre, len(valores), valores)
            else:
                tam = self.coincidir("NUMBER")
                self.coincidir_valor("]")
                self.coincidir_valor(";")
                return NodoDeclaracionArray(tipo, nombre, tam[1])
        self.coincidir_valor("=")
        expr = self.expresion()
        self.coincidir_valor(";")
        return NodoAsignacion(tipo, nombre, expr, es_declaracion=True)

    def lista_valores(self):
        vals = [self.expresion()]
        while self.actual() and self.actual()[1] == ',':
            self.coincidir_valor(",")
            vals.append(self.expresion())
        return vals

    def instruccion_identificador(self):
        nombre = self.coincidir("IDENTIFIER")
        if self.actual() and self.actual()[1] == '(':
            self.coincidir_valor("(")
            args = self.argumentos()
            self.coincidir_valor(")")
            self.coincidir_valor(";")
            return NodoLlamadaFuncion(nombre[1], args)
        if self.actual() and self.actual()[1] == '[':
            self.coincidir_valor("[")
            indice = self.expresion()
            self.coincidir_valor("]")
            self.coincidir_valor("=")
            expr = self.expresion()
            self.coincidir_valor(";")
            return NodoAsignacionArray(nombre, indice, expr)
        if self.actual() and self.actual()[1] in ('++', '--'):
            op = self.actual()[1]; self.pos += 1
            self.coincidir_valor(";")
            return NodoIncrementoDecremento(nombre, op)
        self.coincidir_valor("=")
        expr = self.expresion()
        self.coincidir_valor(";")
        return NodoAsignacion(None, nombre, expr, es_declaracion=False)

    def sentencia_return(self):
        self.coincidir_valor("return")
        if self.actual() and self.actual()[1] == ';':
            self.coincidir_valor(";"); return NodoRetorno(None)
        expr = self.expresion(); self.coincidir_valor(";")
        return NodoRetorno(expr)

    def sentencia_if(self):
        self.coincidir_valor("if"); self.coincidir_valor("(")
        cond = self.expresion(); self.coincidir_valor(")")
        self.coincidir_valor("{"); cuerpo_if = self.cuerpo(); self.coincidir_valor("}")
        cuerpo_else = None
        if self.actual() and self.actual()[1] == 'else':
            self.coincidir_valor("else"); self.coincidir_valor("{")
            cuerpo_else = self.cuerpo(); self.coincidir_valor("}")
        return NodoIf(cond, cuerpo_if, cuerpo_else)

    def sentencia_while(self):
        self.coincidir_valor("while"); self.coincidir_valor("(")
        cond = self.expresion(); self.coincidir_valor(")")
        self.coincidir_valor("{"); cuerpo = self.cuerpo(); self.coincidir_valor("}")
        return NodoWhile(cond, cuerpo)

    def sentencia_for(self):
        self.coincidir_valor("for"); self.coincidir_valor("(")
        init = None
        if self.actual() and self.actual()[1] != ';':
            if self.actual()[0] == 'KEYWORDS':
                init = self.declaracion()
            else:
                init = self.instruccion_identificador()
        else:
            self.coincidir_valor(";")
        condicion = None
        if self.actual() and self.actual()[1] != ';':
            condicion = self.expresion()
        self.coincidir_valor(";")
        incremento = None
        if self.actual() and self.actual()[1] != ')':
            nom = self.coincidir("IDENTIFIER")
            if self.actual() and self.actual()[1] in ('++', '--'):
                op = self.actual()[1]; self.pos += 1
                incremento = NodoIncrementoDecremento(nom, op)
            else:
                self.coincidir_valor("=")
                expr = self.expresion()
                incremento = NodoAsignacion(None, nom, expr, es_declaracion=False)
        self.coincidir_valor(")"); self.coincidir_valor("{")
        cuerpo = self.cuerpo(); self.coincidir_valor("}")
        return NodoFor(init, condicion, incremento, cuerpo)

    def sentencia_print(self):
        self.coincidir_valor("print"); self.coincidir_valor("(")
        expr = self.expresion(); self.coincidir_valor(")"); self.coincidir_valor(";")
        return NodoPrint(expr)

    def sentencia_printf(self):
        self.coincidir_valor("printf"); self.coincidir_valor("(")
        expr = self.expresion(); self.coincidir_valor(")"); self.coincidir_valor(";")
        return NodoPrintf(expr)

    def expresion(self): return self.or_expr()

    def or_expr(self):
        izq = self.and_expr()
        while self.actual() and self.actual()[1] == '||':
            op = self.actual(); self.pos += 1
            izq = NodoOperacion(izq, op, self.and_expr())
        return izq

    def and_expr(self):
        izq = self.comparacion()
        while self.actual() and self.actual()[1] == '&&':
            op = self.actual(); self.pos += 1
            izq = NodoOperacion(izq, op, self.comparacion())
        return izq

    def comparacion(self):
        izq = self.suma()
        while self.actual() and self.actual()[1] in ('==','!=','<','>','<=','>='):
            op = self.actual(); self.pos += 1
            izq = NodoOperacion(izq, op, self.suma())
        return izq

    def suma(self):
        izq = self.producto()
        while self.actual() and self.actual()[1] in ('+', '-'):
            op = self.actual(); self.pos += 1
            izq = NodoOperacion(izq, op, self.producto())
        return izq

    def producto(self):
        izq = self.unario()
        while self.actual() and self.actual()[1] in ('*', '/'):
            op = self.actual(); self.pos += 1
            izq = NodoOperacion(izq, op, self.unario())
        return izq

    def unario(self):
        if self.actual() and self.actual()[1] == '!':
            self.pos += 1; return NodoNegacion(self.unario())
        if self.actual() and self.actual()[1] == '-':
            self.pos += 1
            return NodoOperacion(NodoNumero(('NUMBER','0')), ('OPERATORS','-'), self.unario())
        return self.primario()

    def primario(self):
        t = self.actual()
        if t is None: raise SyntaxError("Se esperaba expresión pero llegó fin de archivo")
        if t[0] == 'NUMBER':
            self.pos += 1
            return NodoFloat(t) if '.' in t[1] else NodoNumero(t)
        if t[0] == 'STRING':
            self.pos += 1; return NodoString(t)
        if t[0] == 'KEYWORDS' and t[1] in ('true','false'):
            self.pos += 1; return NodoBoolean(t)
        if t[1] == '(':
            self.pos += 1; expr = self.expresion(); self.coincidir_valor(")"); return expr
        if t[0] == 'IDENTIFIER':
            self.pos += 1
            if self.actual() and self.actual()[1] == '(':
                self.coincidir_valor("("); args = self.argumentos(); self.coincidir_valor(")")
                return NodoLlamadaFuncion(t[1], args)
            if self.actual() and self.actual()[1] == '[':
                self.coincidir_valor("["); idx = self.expresion(); self.coincidir_valor("]")
                return NodoAccesoArray(t, idx)
            return NodoIdentificador(t)
        raise SyntaxError(f"Expresión no válida: {t}")

    def argumentos(self):
        args = []
        if self.actual() and self.actual()[1] == ')': return args
        args.append(self.expresion())
        while self.actual() and self.actual()[1] == ',':
            self.coincidir_valor(","); args.append(self.expresion())
        return args

# ─────────────────────────────────────────────────────────────
# SERIALIZAR AST
# ─────────────────────────────────────────────────────────────
def serializar_ast(nodo):
    if nodo is None: return None
    t = type(nodo).__name__
    if isinstance(nodo, NodoPrograma):
        return {'tipo':t, 'globales': [serializar_ast(g) for g in nodo.globales],'funciones':[serializar_ast(f) for f in nodo.funciones],'main':serializar_ast(nodo.main)}
    if isinstance(nodo, NodoFuncion):
        return {'tipo':t,'nombre':nodo.nombre[1],'retorno':nodo.tipo_retorno[1],
                'parametros':[serializar_ast(p) for p in nodo.parametros],
                'cuerpo':[serializar_ast(c) for c in nodo.cuerpo]}
    if isinstance(nodo, NodoParametro):
        return {'tipo':t,'nombre':nodo.nombre[1],'tipo_dato':nodo.tipo[1],'es_array':nodo.es_array}
    if isinstance(nodo, NodoAsignacion):
        return {'tipo':t,'nombre':nodo.nombre[1],'declaracion':nodo.es_declaracion,
                'expresion':serializar_ast(nodo.expresion)}
    if isinstance(nodo, NodoDeclaracionArray):
        return {'tipo':t,'nombre':nodo.nombre[1],'tipo_dato':nodo.tipo[1],'tamanio':nodo.tamanio}
    if isinstance(nodo, NodoAsignacionArray):
        return {'tipo':t,'nombre':nodo.nombre[1],'indice':serializar_ast(nodo.indice),
                'expresion':serializar_ast(nodo.expresion)}
    if isinstance(nodo, NodoAccesoArray):
        return {'tipo':t,'nombre':nodo.nombre[1],'indice':serializar_ast(nodo.indice)}
    if isinstance(nodo, NodoOperacion):
        return {'tipo':t,'operador':nodo.operador[1],'izquierda':serializar_ast(nodo.izquierda),
                'derecha':serializar_ast(nodo.derecha)}
    if isinstance(nodo, NodoNegacion):
        return {'tipo':t,'expresion':serializar_ast(nodo.expresion)}
    if isinstance(nodo, NodoIf):
        return {'tipo':t,'condicion':serializar_ast(nodo.condicion),
                'cuerpo_if':[serializar_ast(c) for c in nodo.cuerpo_if],
                'cuerpo_else':[serializar_ast(c) for c in nodo.cuerpo_else] if nodo.cuerpo_else else None}
    if isinstance(nodo, NodoWhile):
        return {'tipo':t,'condicion':serializar_ast(nodo.condicion),
                'cuerpo':[serializar_ast(c) for c in nodo.cuerpo]}
    if isinstance(nodo, NodoFor):
        return {'tipo':t,'init':serializar_ast(nodo.init),'condicion':serializar_ast(nodo.condicion),
                'incremento':serializar_ast(nodo.incremento),
                'cuerpo':[serializar_ast(c) for c in nodo.cuerpo]}
    if isinstance(nodo, NodoRetorno):
        return {'tipo':t,'expresion':serializar_ast(nodo.expresion)}
    if isinstance(nodo, NodoIdentificador): return {'tipo':t,'nombre':nodo.nombre[1]}
    if isinstance(nodo, (NodoNumero, NodoFloat, NodoString, NodoBoolean)):
        return {'tipo':t,'valor':nodo.valor[1]}
    if isinstance(nodo, NodoLlamadaFuncion):
        return {'tipo':t,'nombre':nodo.nombre_funcion,
                'argumentos':[serializar_ast(a) for a in nodo.argumentos]}
    if isinstance(nodo, (NodoPrint, NodoPrintf)):
        return {'tipo':t,'expresion':serializar_ast(nodo.expresion)}
    if isinstance(nodo, NodoIncrementoDecremento):
        return {'tipo':t,'nombre':nodo.nombre[1],'operador':nodo.operador}
    return {'tipo':t}

# ─────────────────────────────────────────────────────────────
# PIPELINE COMPLETO
# ─────────────────────────────────────────────────────────────
def compilar_codigo(codigo: str):
    res = {"tokens":[],"ast":{},"ast_optimizado":{},"tabla_simbolos":{},
           "errores_semanticos":[],"codigo_python":"","codigo_java":"",
           "codigo_ensamblador":"","codigo_c":"","pasos":[],"exito":False}
    pasos = res["pasos"]

    pasos.append("Paso 1: Análisis léxico...")
    try:
        tokens = identificar_tokens(codigo)
        res["tokens"] = [{"tipo":t,"valor":v} for t,v in tokens]
        pasos.append(f"{len(tokens)} tokens encontrados")
    except Exception as e:
        pasos.append(f"Error léxico: {e}"); return res

    pasos.append("Paso 2: Análisis sintáctico...")
    try:
        ast = Parser(tokens).parse()
        res["ast"] = serializar_ast(ast)
        pasos.append("AST construido correctamente")
    except SyntaxError as e:
        pasos.append(f"Error sintáctico: {e}"); return res

    pasos.append("Paso 3: Análisis semántico...")
    sem = AnalizadorSemantico()
    try:
        sem.analizar(ast)
        res["tabla_simbolos"] = sem.tabla.serializar()
        pasos.extend(sem.pasos)
        pasos.append(f"Semántica OK — {len(sem.tabla.simbolos)} símbolo(s)")
    except Exception as e:
        res["errores_semanticos"].append(str(e))
        pasos.append(f"{e}")

    pasos.append("Paso 4: Optimización...")
    try:
        ast_opt = ast.optimizar()
        res["ast_optimizado"] = serializar_ast(ast_opt)
        pasos.append("Optimización completada")
    except Exception as e:
        ast_opt = ast; pasos.append(f"Sin optimización: {e}")

    for label, key, method in [
        ("Paso 5: Python",      "codigo_python",      "traducirPy"),
        ("Paso 6: Java",         "codigo_java",        "traducirJava"),
        ("Paso 7: Ensamblador", "codigo_ensamblador", "generarCodigo"),
        ("Paso 8: C",           "codigo_c",           "traducirC")
    ]:
        pasos.append(f"{label}...")
        try:
            res[key] = getattr(ast_opt, method)()
            pasos.append("Generado")
        except Exception as e:
            pasos.append(f"Error: {e}")

    pasos.append("¡Compilación completada!")
    res["exito"] = True
    return res

# ─────────────────────────────────────────────────────────────
# ENDPOINTS FASTAPI
# ─────────────────────────────────────────────────────────────
class CodigoRequest(BaseModel):
    codigo: str

class ArchivoRequest(BaseModel):
    nombre: str
    contenido: str
    formato: str = "cpp"  # "cpp", "asm", "py", "java", etc.

ARCHIVOS_DIR = "archivos"
os.makedirs(ARCHIVOS_DIR, exist_ok=True)


def ejecutar_comando(comando, cwd=None):
    try:
        resultado = subprocess.run(comando, cwd=cwd, capture_output=True, text=True, check=True)
        return resultado.stdout
    except subprocess.CalledProcessError as e:
        salida = e.stderr or e.stdout or str(e)
        raise RuntimeError(f"Error al ejecutar {' '.join(comando)}: {salida.strip()}")


def ensamblar_asm_a_obj(asm_path, obj_path):
    if shutil.which("nasm"):
        ejecutar_comando(["nasm", "-f", "win32", "-o", obj_path, asm_path])
        return
    if shutil.which("gcc"):
        ejecutar_comando(["gcc", "-c", "-x", "assembler", "-o", obj_path, asm_path])
        return
    if shutil.which("clang"):
        ejecutar_comando(["clang", "-c", "-x", "assembler", "-o", obj_path, asm_path])
        return
    if shutil.which("ml"):
        ejecutar_comando(["ml", "/c", f"/Fo{obj_path}", asm_path])
        return
    raise RuntimeError("No se encontró ningún ensamblador compatible en el servidor.")


def link_obj_a_exe(obj_path, exe_path):
    if shutil.which("gcc"):
        ejecutar_comando(["gcc", "-o", exe_path, obj_path])
        return
    if shutil.which("clang"):
        ejecutar_comando(["clang", "-o", exe_path, obj_path])
        return
    if shutil.which("link"):
        ejecutar_comando(["link", f"/OUT:{exe_path}", obj_path])
        return
    if shutil.which("cl"):
        ejecutar_comando(["cl", "/Fe:" + exe_path, obj_path])
        return
    raise RuntimeError("No se encontró ningún enlazador compatible en el servidor.")


@app.get("/")
def root():
    return {
        "mensaje": "Compilador API v2.0",
        "soporta": ["if/else","while","for","arrays","strings","booleans",
                    "operadores ==!=<><=>=","negacion !","incremento ++ --",
                    "comentarios // /**/","llamadas a función","ámbitos"]
    }

@app.post("/compilar")
def compilar(req: CodigoRequest):
    if not req.codigo.strip():
        raise HTTPException(400, "El código no puede estar vacío")
    return compilar_codigo(req.codigo)

@app.post("/compilar-guardar-asm")
def compilar_guardar_asm(req: CodigoRequest):
    """Compila código y guarda automáticamente el ensamblador en .asm"""
    if not req.codigo.strip():
        raise HTTPException(400, "El código no puede estar vacío")
    
    resultado = compilar_codigo(req.codigo)
    
    if not resultado["exito"]:
        raise HTTPException(400, "Compilación fallida: " + str(resultado["errores_semanticos"]))
    
    # Generar nombre de archivo basado en timestamp
    import time
    nombre_archivo = f"programa_{int(time.time())}"
    
    try:
        # Guardar ensamblador
        with open(os.path.join(ARCHIVOS_DIR, nombre_archivo + ".asm"), 'w', encoding='utf-8') as f:
            f.write(resultado["codigo_ensamblador"])
        
        resultado["archivo_guardado"] = nombre_archivo + ".asm"
        resultado["ruta"] = os.path.join(ARCHIVOS_DIR, nombre_archivo + ".asm")
        return resultado
    except Exception as e:
        raise HTTPException(500, f"Error al guardar: {str(e)}")

@app.post("/tokens")
def obtener_tokens(req: CodigoRequest):
    try:
        tokens = identificar_tokens(req.codigo)
        return {"tokens": [{"tipo": t, "valor": v} for t, v in tokens]}
    except Exception as e:
        raise HTTPException(400, str(e))

@app.post("/archivos/guardar")
def guardar_archivo(req: ArchivoRequest):
    # Determinar extensión basada en formato
    extensiones = {"cpp": ".cpp", "asm": ".asm", "py": ".py", "java": ".java", "c": ".c"}
    ext = extensiones.get(req.formato, ".cpp")
    nombre = req.nombre if req.nombre.endswith(ext) else req.nombre + ext
    try:
        with open(os.path.join(ARCHIVOS_DIR, nombre), 'w', encoding='utf-8') as f:
            f.write(req.contenido)
        return {"mensaje": f"'{nombre}' guardado", "nombre": nombre, "formato": req.formato}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.post("/compilar-crear-ejecutable")
def compilar_crear_ejecutable(req: CodigoRequest):
    if not req.codigo.strip():
        raise HTTPException(400, "El código no puede estar vacío")

    resultado = compilar_codigo(req.codigo)
    if not resultado.get("exito"):
        raise HTTPException(400, "Compilación fallida")

    if not shutil.which("gcc"):
        raise HTTPException(500, "GCC no encontrado. Instala MinGW/MSYS2.")

    codigo_c = resultado.get("codigo_c", "")
    if not codigo_c:
        raise HTTPException(400, "No se generó código C")

    # ── Inyectar scanf para variables marcadas como "entrada del usuario" ──
    import re
    def inyectar_scanf(c_code):
        lineas = c_code.split("\n")
        nuevas = []
        for linea in lineas:
            nuevas.append(linea)
            # Detectar líneas como: int numero = 0; // entrada del usuario
            m = re.match(r'\s*(int|float)\s+(\w+)\s*=\s*\S+;\s*//\s*entrada del usuario', linea)
            if m:
                tipo  = m.group(1)
                var   = m.group(2)
                fmt   = "%d" if tipo == "int" else "%f"
                indent = len(linea) - len(linea.lstrip())
                pad   = " " * indent
                nuevas.append(f'{pad}printf("Ingresa {var}: ");')
                nuevas.append(f'{pad}scanf("{fmt}", &{var});')
        return "\n".join(nuevas)

    codigo_c = inyectar_scanf(codigo_c)

    timestamp = int(time.time())
    base     = f"programa_{timestamp}"
    c_ruta   = os.path.join(ARCHIVOS_DIR, base + ".c")
    asm_ruta = os.path.join(ARCHIVOS_DIR, base + ".s")
    exe_ruta = os.path.join(ARCHIVOS_DIR, base + ".exe")

    try:
        with open(c_ruta, 'w', encoding='utf-8') as f:
            f.write(codigo_c)

        proc_asm = subprocess.run(
            ["gcc", "-S", "-masm=intel", c_ruta, "-o", asm_ruta],
            capture_output=True, text=True
        )
        if proc_asm.returncode != 0:
            raise HTTPException(500, f"Error generando ASM: {proc_asm.stderr}")

        with open(asm_ruta, 'r', encoding='utf-8') as f:
            asm_real = f.read()

        proc_exe = subprocess.run(
            ["gcc", c_ruta, "-o", exe_ruta, "-lm"],
            capture_output=True, text=True
        )
        if proc_exe.returncode != 0:
            raise HTTPException(500, f"Error compilando: {proc_exe.stderr}")

        asm_guardado = base + ".asm"
        with open(os.path.join(ARCHIVOS_DIR, asm_guardado), 'w', encoding='utf-8') as f:
            f.write(asm_real)

        return FileResponse(
            exe_ruta,
            media_type="application/octet-stream",
            filename=base + ".exe"
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))
    finally:
        for ruta in [c_ruta, asm_ruta]:
            if os.path.exists(ruta):
                os.remove(ruta)

@app.get("/archivos")
def listar_archivos():
    return {"archivos": os.listdir(ARCHIVOS_DIR)}

@app.get("/archivos/descargar/{nombre}")
def descargar_archivo(nombre: str):
    ruta = os.path.join(ARCHIVOS_DIR, nombre)
    if not os.path.exists(ruta):
        raise HTTPException(404, "Archivo no encontrado")
    return FileResponse(ruta, filename=nombre, media_type='application/octet-stream')

@app.get("/archivos/{nombre}")
def cargar_archivo(nombre: str):
    ruta = os.path.join(ARCHIVOS_DIR, nombre)
    if not os.path.exists(ruta):
        raise HTTPException(404, "Archivo no encontrado")
    with open(ruta, 'r', encoding='utf-8') as f:
        return {"nombre": nombre, "contenido": f.read()}

@app.delete("/archivos/{nombre}")
def eliminar_archivo(nombre: str):
    ruta = os.path.join(ARCHIVOS_DIR, nombre)
    if not os.path.exists(ruta):
        raise HTTPException(404, "Archivo no encontrado")
    os.remove(ruta)
    return {"mensaje": f"'{nombre}' eliminado"}