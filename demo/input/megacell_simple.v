`timescale 1ns/10ps

// Simple combinational MegaCell netlist built from ASAP7 RVT stdCells.
// Functionally:
//   Y  = ((A & B) | (C ^ D)) & ~(A & C)
//   YN = ~Y
module MegaCell_simple (
    Y,
    YN,
    A,
    B,
    C,
    D
);
    output Y;
    output YN;
    input A;
    input B;
    input C;
    input D;

    wire n_ab;
    wire n_cd_xor;
    wire n_or;
    wire n_ac_nand;

    AND2x2_ASAP7_75t_R u_and_ab (
        .Y(n_ab),
        .A(A),
        .B(B)
    );

    XOR2x1_ASAP7_75t_R u_xor_cd (
        .Y(n_cd_xor),
        .A(C),
        .B(D)
    );

    OR2x2_ASAP7_75t_R u_or_mid (
        .Y(n_or),
        .A(n_ab),
        .B(n_cd_xor)
    );

    NAND2x1_ASAP7_75t_R u_nand_ac (
        .Y(n_ac_nand),
        .A(A),
        .B(C)
    );

    AND2x2_ASAP7_75t_R u_and_out (
        .Y(Y),
        .A(n_or),
        .B(n_ac_nand)
    );

    INVx1_ASAP7_75t_R u_inv_out (
        .Y(YN),
        .A(Y)
    );
endmodule
