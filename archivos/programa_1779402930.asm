	.file	"programa_1779402930.c"
	.intel_syntax noprefix
	.text
	.section .rdata,"dr"
.LC0:
	.ascii "%d\0"
	.text
	.globl	main
	.def	main;	.scl	2;	.type	32;	.endef
	.seh_proc	main
main:
	push	rbp
	.seh_pushreg	rbp
	mov	rbp, rsp
	.seh_setframe	rbp, 0
	sub	rsp, 48
	.seh_stackalloc	48
	.seh_endprologue
	call	__main
	mov	DWORD PTR -4[rbp], 0
	mov	eax, DWORD PTR -4[rbp]
	add	eax, eax
	mov	DWORD PTR -8[rbp], eax
	cmp	DWORD PTR -8[rbp], 10
	jle	.L2
	mov	eax, DWORD PTR -8[rbp]
	lea	rcx, .LC0[rip]
	mov	edx, eax
	call	__mingw_printf
	jmp	.L3
.L2:
	lea	rax, .LC0[rip]
	mov	edx, 0
	mov	rcx, rax
	call	__mingw_printf
.L3:
	mov	eax, 0
	add	rsp, 48
	pop	rbp
	ret
	.seh_endproc
	.def	__main;	.scl	2;	.type	32;	.endef
	.ident	"GCC: (Rev13, Built by MSYS2 project) 15.2.0"
