#!/usr/bin/env python3
"""
Bytecode extraction utility for SANDBOX_COUNT operations testing.

This script extracts bytecode from Python source code with SANDBOX_COUNT
opcodes filtered and formatted for comparison.

Features:
- Filter to show only SANDBOX_COUNT opcodes or all opcodes (--all)
- Shows source code line with highlighting for the portion that generates each opcode
- Shows AST node type for each opcode (--show-ast-types)
- Detects folded constants
- Calculates total operations count from SANDBOX_COUNT opcodes
- Compare bytecode outputs between files
"""

import ast
import dis
import sys
import opcode
import argparse
from pathlib import Path


# PyCF_SANDBOX_COUNT flag value (must match Include/cpython/compile.h)
PyCF_SANDBOX_COUNT = 0x8000


def fold_constants(node):
    """
    Recursively fold constant expressions in an AST.
    
    Folds BinOp and UnaryOp nodes with Constant operands into single Constant nodes.
    Preserves position (lineno, col_offset, end_lineno, end_col_offset) from the original outermost node.
    
    Args:
        node: An AST node to fold
        
    Returns:
        The folded AST node (Constant if foldable, otherwise the original node with folded children)
    """
    if isinstance(node, ast.Constant):
        return node
    
    if isinstance(node, ast.BinOp):
        # Recursively fold left and right operands
        left = fold_constants(node.left)
        right = fold_constants(node.right)
        
        # Check if both operands are now constants
        if isinstance(left, ast.Constant) and isinstance(right, ast.Constant):
            try:
                if isinstance(node.op, ast.Add):
                    result = left.value + right.value
                elif isinstance(node.op, ast.Sub):
                    result = left.value - right.value
                elif isinstance(node.op, ast.Mult):
                    result = left.value * right.value
                elif isinstance(node.op, ast.Div):
                    result = left.value / right.value
                elif isinstance(node.op, ast.FloorDiv):
                    result = left.value // right.value
                elif isinstance(node.op, ast.Mod):
                    result = left.value % right.value
                elif isinstance(node.op, ast.Pow):
                    result = left.value ** right.value
                elif isinstance(node.op, ast.LShift):
                    result = left.value << right.value
                elif isinstance(node.op, ast.RShift):
                    result = left.value >> right.value
                elif isinstance(node.op, ast.BitOr):
                    result = left.value | right.value
                elif isinstance(node.op, ast.BitXor):
                    result = left.value ^ right.value
                elif isinstance(node.op, ast.BitAnd):
                    result = left.value & right.value
                elif isinstance(node.op, ast.MatMult):
                    result = left.value @ right.value
                else:
                    # Unknown operator, can't fold
                    node.left = left
                    node.right = right
                    return node
                
                # Create new Constant node with result, preserving position from original BinOp
                folded = ast.Constant(value=result)
                folded.lineno = node.lineno
                folded.col_offset = node.col_offset
                folded.end_lineno = node.end_lineno
                folded.end_col_offset = node.end_col_offset
                return folded
            except (TypeError, ValueError, ZeroDivisionError):
                # Can't fold (e.g., incompatible types, division by zero)
                node.left = left
                node.right = right
                return node
        else:
            # Not foldable, but update children
            node.left = left
            node.right = right
            return node
    
    if isinstance(node, ast.UnaryOp):
        # Recursively fold the operand
        operand = fold_constants(node.operand)
        
        if isinstance(operand, ast.Constant):
            try:
                if isinstance(node.op, ast.UAdd):
                    result = +operand.value
                elif isinstance(node.op, ast.USub):
                    result = -operand.value
                elif isinstance(node.op, ast.Invert):
                    result = ~operand.value
                elif isinstance(node.op, ast.Not):
                    result = not operand.value
                else:
                    # Unknown operator, can't fold
                    node.operand = operand
                    return node
                
                # Create new Constant node with result, preserving position from original UnaryOp
                folded = ast.Constant(value=result)
                folded.lineno = node.lineno
                folded.col_offset = node.col_offset
                folded.end_lineno = node.end_lineno
                folded.end_col_offset = node.end_col_offset
                return folded
            except (TypeError, ValueError):
                # Can't fold
                node.operand = operand
                return node
        else:
            # Not foldable, but update operand
            node.operand = operand
            return node
    
    # For other node types, recursively fold children but preserve the node
    for field, value in ast.iter_fields(node):
        if isinstance(value, ast.AST):
            setattr(node, field, fold_constants(value))
        elif isinstance(value, list):
            new_list = []
            for item in value:
                if isinstance(item, ast.AST):
                    new_list.append(fold_constants(item))
                else:
                    new_list.append(item)
            setattr(node, field, new_list)
    
    return node


class OpcodeInfo:
    """Container for opcode information including source position and AST type."""
    __slots__ = ('offset', 'opname', 'oparg', 'line', 'col', 'end_col', 'ast_node_type', 'is_folded')
    
    def __init__(self, offset, opname, oparg, line, col, end_col, ast_node_type="-", is_folded=False):
        self.offset = offset
        self.opname = opname
        self.oparg = oparg
        self.line = line
        self.col = col
        self.end_col = end_col
        self.ast_node_type = ast_node_type
        self.is_folded = is_folded
    
    def __repr__(self):
        return f"OpcodeInfo({self.offset}, {self.opname!r}, {self.oparg}, L{self.line}:{self.col}-{self.end_col}, {self.ast_node_type})"


def build_ast_position_map(source_code):
    """
    Build a mapping from source positions to optimized AST node types.
    
    This applies constant folding to the AST to match what the compiler does,
    then builds a position-to-node-type mapping.
    
    Returns:
        dict: {(line, col, end_col): node_type} mapping
    """
    try:
        tree = ast.parse(source_code)
        # Apply constant folding to match compiler's optimization
        tree = fold_constants(tree)
    except SyntaxError:
        return {}
    
    position_map = {}
    
    def add_node_positions(node):
        """Recursively add node positions to the map."""
        if hasattr(node, 'lineno') and hasattr(node, 'col_offset'):
            line = node.lineno
            col = node.col_offset
            end_line = getattr(node, 'end_lineno', line)
            end_col = getattr(node, 'end_col_offset', col)
            
            # Use the end line's column if available, otherwise use col
            key_end_col = end_col if end_line == line else col + 1
            
            node_type = type(node).__name__
            key = (line, col, key_end_col)
            
            # Store the node type (prefer more specific types if position overlaps)
            position_map[key] = node_type
        
        # Recurse into child nodes
        for child in ast.iter_child_nodes(node):
            add_node_positions(child)
    
    add_node_positions(tree)
    return position_map


def find_ast_node_type(position_map, line, col, end_col, opname, oparg):
    """
    Find the AST node type for a given position.
    
    Args:
        position_map: dict of {(line, col, end_col): node_type}
        line: line number (1-indexed)
        col: column offset
        end_col: end column offset
        opname: opcode name
        oparg: opcode argument
    
    Returns:
        (node_type, is_folded) tuple
    """
    if line is None or not position_map:
        return ("-", False)
    
    # Try exact match first
    exact_key = (line, col, end_col)
    if exact_key in position_map:
        node_type = position_map[exact_key]
        # Check if this is a folded constant (SANDBOX_COUNT with accumulated count)
        is_folded = (opname == 'SANDBOX_COUNT' and oparg is not None and oparg > 1)
        return (node_type, is_folded)
    
    # Try matching by position range (find smallest enclosing node)
    best_match = None
    best_size = float('inf')
    
    for (map_line, map_col, map_end_col), node_type in position_map.items():
        if map_line == line:
            # Check if this position is within the node's range
            if map_col <= col and end_col <= map_end_col:
                size = map_end_col - map_col
                if size < best_size:
                    best_size = size
                    best_match = node_type
    
    if best_match:
        is_folded = (opname == 'SANDBOX_COUNT' and oparg is not None and oparg > 1)
        return (best_match, is_folded)
    
    return ("-", False)


def extract_bytecode(source_code, filename="<test>", all_opcodes=False, include_ast_types=False):
    """
    Compile source code and extract bytecode with SANDBOX_COUNT filtering.
    
    Args:
        source_code: Python source code as string
        filename: Name for the code object (for display)
        all_opcodes: If True, return all opcodes; if False, only SANDBOX_COUNT opcodes
        include_ast_types: If True, include AST node type information
    
    Returns:
        List of OpcodeInfo objects with source position information
    """
    # Build AST position map if needed
    position_map = build_ast_position_map(source_code) if include_ast_types else {}
    
    try:
        # Compile with SANDBOX_COUNT flag (always use default optimization)
        flags = PyCF_SANDBOX_COUNT
        code = compile(source_code, filename, 'exec', flags=flags, optimize=-1)
        
        # Extract instructions from top-level and all nested code objects
        result = []
        seen_codes = set()  # Track processed code objects to avoid duplicates
        
        def extract_from_code(code_obj, code_name="<module>"):
            """Recursively extract instructions from a code object and its nested code objects."""
            if id(code_obj) in seen_codes:
                return
            seen_codes.add(id(code_obj))
            
            # Add a header for nested code objects
            if code_name != "<module>":
                result.append(OpcodeInfo(
                    0, '---', f"Code: {code_name}", None, None, None, "-", False
                ))
            
            # Extract all instructions from this code object
            instructions = list(dis.get_instructions(code_obj))
            
            for instr in instructions:
                # Get position info if available (Python 3.11+)
                if instr.positions:
                    line = instr.positions.lineno
                    col = instr.positions.col_offset
                    end_col = instr.positions.end_col_offset
                else:
                    line = instr.starts_line
                    col = None
                    end_col = None
                
                if all_opcodes or instr.opname == 'SANDBOX_COUNT':
                    # Find AST node type if requested
                    ast_node_type = "-"
                    is_folded = False
                    if include_ast_types and line is not None:
                        ast_node_type, is_folded = find_ast_node_type(
                            position_map, line, col, end_col, instr.opname, instr.arg
                        )
                    
                    result.append(OpcodeInfo(
                        instr.offset, instr.opname, instr.arg, line, col, end_col,
                        ast_node_type, is_folded
                    ))
                
                # Check if this instruction references a code object (for nested functions/classes)
                if instr.opname in ('LOAD_CONST', 'MAKE_FUNCTION', 'MAKE_CELL'):
                    # The arg might reference a constant which could be a code object
                    if hasattr(code_obj, 'co_consts') and instr.arg is not None:
                        if 0 <= instr.arg < len(code_obj.co_consts):
                            const = code_obj.co_consts[instr.arg]
                            if isinstance(const, type(code_obj)):
                                # Found a nested code object, extract it recursively
                                extract_from_code(const, const.co_name)
            
            # Also check all constants for code objects (some might not be directly referenced)
            if hasattr(code_obj, 'co_consts'):
                for const in code_obj.co_consts:
                    if isinstance(const, type(code_obj)):
                        extract_from_code(const, const.co_name)
        
        extract_from_code(code, "<module>")
        return result
    except SyntaxError as e:
        return [OpcodeInfo(0, 'SYNTAX_ERROR', str(e), e.lineno if hasattr(e, 'lineno') else None, 
                          getattr(e, 'offset', None), None)]
    except Exception as e:
        return [OpcodeInfo(0, 'ERROR', str(e), None, None, None)]


def format_bytecode(ops, source_lines=None, highlight=False, use_color=True, show_ast_types=False):
    """
    Format bytecode operations for display/comparison.
    
    Args:
        ops: List of OpcodeInfo objects
        source_lines: List of source code lines (for highlighting)
        highlight: If True, show source line with highlighting on the right
        use_color: If True, use ANSI color codes for highlighting
        show_ast_types: If True, show AST node type column
    """
    # ANSI color codes
    BOLD = '\033[1m' if use_color else ''
    BG_YELLOW = '\033[43m' if use_color else ''  # Yellow background
    FG_BLACK = '\033[30m' if use_color else ''   # Black text on light background
    DIM = '\033[2m' if use_color else ''
    RESET = '\033[0m' if use_color else ''
    
    # First pass: calculate column widths
    max_offset_width = 4  # offset is typically up to 4 digits
    max_opname_width = 0
    max_arg_width = 4     # minimum width for arg column
    max_ast_type_width = 0
    
    for op in ops:
        if op.opname not in ('SYNTAX_ERROR', 'ERROR'):
            max_opname_width = max(max_opname_width, len(op.opname))
            arg_len = len(str(op.oparg)) if op.oparg is not None else 4  # "None"
            max_arg_width = max(max_arg_width, arg_len)
            if show_ast_types:
                # When folded, it displays as "Constant [folded]"
                if op.is_folded:
                    ast_type_display = "Constant [folded]"
                else:
                    ast_type_display = op.ast_node_type
                max_ast_type_width = max(max_ast_type_width, len(ast_type_display))
    
    # Add padding
    max_opname_width = max(max_opname_width, 12)  # minimum for readability
    max_ast_type_width = max(max_ast_type_width, 8)  # minimum for "Constant"
    
    # Column positions (using spaces, not tabs)
    OFFSET_COL = 0
    LINE_COL = max_offset_width + 2
    AST_TYPE_COL = LINE_COL + 6  # Always define this
    
    if show_ast_types:
        OPNAME_COL = AST_TYPE_COL + max_ast_type_width + 1
    else:
        OPNAME_COL = LINE_COL + 6
    
    ARG_COL = OPNAME_COL + max_opname_width + 1
    SEP_COL = ARG_COL + max_arg_width + 2
    
    def pad_to(text, col):
        """Pad text to reach specified column."""
        current_len = len(text)
        if current_len < col:
            return text + ' ' * (col - current_len)
        return text
    
    lines = []
    prev_line_num = None
    prev_col = None
    prev_end_col = None
    
    for op in ops:
        if op.opname in ('SYNTAX_ERROR', 'ERROR'):
            lines.append(f"{op.opname}: {op.oparg}")
        else:
            # Build the base line piece by piece with proper spacing
            line_str = f"{op.offset:>{max_offset_width}d}:"
            line_str = pad_to(line_str, LINE_COL)
            
            # Add line number
            if op.line is not None:
                line_str += f"L{op.line:4d} "
            else:
                line_str += "      "
            
            # Add AST node type if requested
            if show_ast_types:
                line_str = pad_to(line_str, AST_TYPE_COL)
                ast_type_display = op.ast_node_type
                # When folded, show as Constant [folded] since that's what it becomes after folding
                if op.is_folded:
                    ast_type_display = "Constant [folded]"
                line_str += ast_type_display
            
            line_str = pad_to(line_str, OPNAME_COL)
            
            # Add opname
            line_str += op.opname
            line_str = pad_to(line_str, ARG_COL)
            
            # Add arg
            if op.oparg is not None:
                line_str += str(op.oparg)
            else:
                line_str += "None"
            
            # Add source on the right if requested and available
            if highlight and source_lines and op.line is not None:
                source_idx = op.line - 1  # lines are 1-indexed
                if 0 <= source_idx < len(source_lines):
                    source_line = source_lines[source_idx]
                    
                    # Check if this is the exact same position as previous
                    is_same_position = (
                        op.line == prev_line_num and 
                        op.col == prev_col and 
                        op.end_col == prev_end_col
                    )
                    
                    if is_same_position:
                        # Same position: don't repeat the source line
                        lines.append(line_str)
                    else:
                        # Different position: show source with highlighting
                        if op.col is not None and op.end_col is not None:
                            if use_color:
                                # Build highlighted source line with background color
                                before = source_line[:op.col]
                                highlight = source_line[op.col:op.end_col]
                                after = source_line[op.end_col:]
                                
                                # Use yellow background with bold black text for highlight
                                highlighted = f"{BOLD}{BG_YELLOW}{FG_BLACK}{highlight}{RESET}"
                                display_source = before + highlighted + after
                                
                                # Truncate if too long for display
                                max_source_len = 70
                                if len(display_source) > max_source_len:
                                    display_source = display_source[:max_source_len-3] + '...'
                                
                                line_str = pad_to(line_str, SEP_COL)
                                line_str += f"{DIM}│{RESET} {display_source}"
                                lines.append(line_str)
                            else:
                                # Non-color mode: show source and add ^^^^ line below
                                line_str = pad_to(line_str, SEP_COL)
                                line_str += f"│ {source_line}"
                                lines.append(line_str)
                                
                                # Build the ^^^^ highlight line
                                highlight_chars = [' '] * len(source_line)
                                start = max(0, op.col)
                                end = min(op.end_col, len(source_line))
                                for i in range(start, end):
                                    highlight_chars[i] = '^'
                                highlight_line = ''.join(highlight_chars)
                                
                                # Add the ^^^^ line with proper spacing
                                spacer = ' ' * SEP_COL
                                lines.append(f"{spacer}│ {highlight_line}")
                        else:
                            # No column info, just show the line
                            line_str = pad_to(line_str, SEP_COL)
                            if use_color:
                                display_source = source_line[:70]
                                if len(source_line) > 70:
                                    display_source += '...'
                                line_str += f"{DIM}│{RESET} {DIM}{display_source}{RESET}"
                            else:
                                line_str += f"│ {source_line}"
                            lines.append(line_str)
                    
                    prev_line_num = op.line
                    prev_col = op.col
                    prev_end_col = op.end_col
                else:
                    lines.append(line_str)
            else:
                lines.append(line_str)
    
    return '\n'.join(lines)


def get_total_operations_count(ops):
    """Calculate total operations count from SANDBOX_COUNT opcodes."""
    total = 0
    for op in ops:
        if op.opname == 'SANDBOX_COUNT' and op.oparg is not None:
            total += op.oparg
    return total


def compare_bytecode(expected_ops, actual_ops):
    """
    Compare two bytecode outputs.
    
    Args:
        expected_ops: List of OpcodeInfo objects
        actual_ops: List of OpcodeInfo objects
    
    Returns:
        (is_equal, diff_message)
    """
    if len(expected_ops) != len(actual_ops):
        return False, f"Length mismatch: expected {len(expected_ops)}, got {len(actual_ops)}"
    
    differences = []
    for i, (exp, act) in enumerate(zip(expected_ops, actual_ops)):
        # Compare key attributes
        if (exp.opname != act.opname or 
            exp.oparg != act.oparg):
            differences.append(f"  Line {i}: expected ({exp.opname}, {exp.oparg}), got ({act.opname}, {act.oparg})")
    
    if differences:
        return False, "Differences found:\n" + '\n'.join(differences)
    
    return True, "Bytecodes match"


def main():
    parser = argparse.ArgumentParser(
        description="Extract and display SANDBOX_COUNT opcodes from Python source code",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s test.py                  # Only SANDBOX_COUNT opcodes
  %(prog)s --all test.py            # All opcodes
  %(prog)s -s test.py               # Show source on the right with highlighting
  %(prog)s --all --show-source test.py  # All opcodes with source
  %(prog)s --show-ast-types test.py     # Show AST node types
  %(prog)s --all --show-source --show-ast-types test.py  # Everything
  %(prog)s --compare a.py b.py      # Compare bytecode of two files

Output format:
  Without --show-source:
    offset: L<line> [AST_TYPE] OPNAME arg
  
  With --show-source:
    Terminal (with colors):
      offset: L<line> [AST_TYPE] OPNAME arg  │ source_code_with_highlighted_portion
      
    Non-terminal/piped (without colors):
      offset: L<line> [AST_TYPE] OPNAME arg  │ source_code_line
                                              │ ^^^^^^^^^^^^
      
  When multiple opcodes are on the same line, the source is only shown once.
  ANSI colors are automatically disabled when output is not a terminal.
  Use --no-color to force disable colors even in terminal.
        """
    )
    
    parser.add_argument('source_file', nargs='?', help='Python source file to analyze')
    parser.add_argument('-a', '--all', action='store_true', dest='all_opcodes',
                       help='Show all opcodes (default: only SANDBOX_COUNT)')
    parser.add_argument('-s', '--show-source', action='store_true',
                       help='Show source code with highlighting for each opcode')
    parser.add_argument('--show-ast-types', action='store_true',
                       help='Show AST node type for each opcode')
    parser.add_argument('--no-color', action='store_true',
                       help='Disable ANSI color codes (use ^^^^ for highlighting)')
    parser.add_argument('--compare', nargs=2, metavar=('FILE1', 'FILE2'),
                       help='Compare bytecode of two files')
    
    args = parser.parse_args()
    
    # Handle compare mode
    if args.compare:
        file1, file2 = args.compare
        source1 = Path(file1).read_text()
        source2 = Path(file2).read_text()
        ops1 = extract_bytecode(source1, file1, all_opcodes=False, include_ast_types=args.show_ast_types)
        ops2 = extract_bytecode(source2, file2, all_opcodes=False, include_ast_types=args.show_ast_types)
        
        is_equal, message = compare_bytecode(ops1, ops2)
        print(message)
        return 0 if is_equal else 1
    
    # Check source file is provided
    if not args.source_file:
        parser.error("No source file specified")
    
    # Read source and extract bytecode
    source = Path(args.source_file).read_text()
    source_lines = source.split('\n')
    
    ops = extract_bytecode(source, args.source_file, args.all_opcodes, args.show_ast_types)
    
    # Determine if we should use colors
    # Use colors by default only if output is a terminal and --no-color is not specified
    use_color = sys.stdout.isatty() and not args.no_color
    
    # Format and print
    print(format_bytecode(ops, source_lines if args.show_source else None, 
                         highlight=args.show_source, use_color=use_color,
                         show_ast_types=args.show_ast_types))
    
    # Print summary
    if not args.all_opcodes:
        print(f"\nTotal operations count: {get_total_operations_count(ops)}")
    else:
        # Count SANDBOX_COUNT ops in the full listing
        sandbox_ops = [op for op in ops if op.opname == 'SANDBOX_COUNT']
        print(f"\nTotal SANDBOX_COUNT operations: {get_total_operations_count(sandbox_ops)}")
    
    return 0


if __name__ == '__main__':
    main()
