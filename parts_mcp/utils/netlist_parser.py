"""
Netlist parsing utilities for KiCad schematic files.
"""
import re
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Set
from collections import defaultdict

logger = logging.getLogger(__name__)


class NetlistParser:
    """Parser for KiCad netlist files."""
    
    def __init__(self, netlist_path: str):
        """Initialize the netlist parser.
        
        Args:
            netlist_path: Path to the netlist file
        """
        self.netlist_path = Path(netlist_path)
        self.components = {}
        self.nets = defaultdict(list)
        self.net_names = {}
        
    def parse(self) -> Dict[str, Any]:
        """Parse the netlist file.
        
        Returns:
            Dictionary with parsed netlist data
        """
        if not self.netlist_path.exists():
            logger.error(f"Netlist file not found: {self.netlist_path}")
            return {"error": "File not found"}
            
        try:
            with open(self.netlist_path, 'r') as f:
                content = f.read()
                
            # Detect format and parse accordingly
            if content.strip().startswith('(export'):
                # KiCad netlist format (S-expression)
                return self._parse_kicad_netlist(content)
            else:
                # Try other formats
                return self._parse_generic_netlist(content)
                
        except Exception as e:
            logger.error(f"Error parsing netlist: {e}")
            return {"error": str(e)}
            
    def _parse_kicad_netlist(self, content: str) -> Dict[str, Any]:
        """Parse KiCad S-expression netlist format.
        
        Args:
            content: Netlist file content
            
        Returns:
            Parsed netlist data
        """
        logger.info("Parsing KiCad netlist format")
        
        # Extract components
        comp_pattern = r'\(comp \(ref ([^)]+)\)\s*\(value ([^)]+)\).*?\)'
        for match in re.finditer(comp_pattern, content, re.DOTALL):
            ref = match.group(1).strip('"')
            value = match.group(2).strip('"')
            
            self.components[ref] = {
                'reference': ref,
                'value': value,
                'pins': []
            }
            
        # Extract nets
        net_pattern = r'\(net \(code (\d+)\) \(name ([^)]+)\)(.*?)\)\s*\)'
        for match in re.finditer(net_pattern, content, re.DOTALL):
            net_code = match.group(1)
            net_name = match.group(2).strip('"/')
            net_content = match.group(3)
            
            self.net_names[net_code] = net_name
            
            # Extract nodes (component pins) in this net
            node_pattern = r'\(node \(ref ([^)]+)\) \(pin ([^)]+)\)\)'
            for node_match in re.finditer(node_pattern, net_content):
                comp_ref = node_match.group(1).strip('"')
                pin = node_match.group(2).strip('"')
                
                self.nets[net_name].append({
                    'component': comp_ref,
                    'pin': pin
                })
                
                # Add pin to component
                if comp_ref in self.components:
                    self.components[comp_ref]['pins'].append({
                        'number': pin,
                        'net': net_name
                    })
                    
        return self._build_result()
        
    def _parse_generic_netlist(self, content: str) -> Dict[str, Any]:
        """Parse generic netlist formats.
        
        Args:
            content: Netlist file content
            
        Returns:
            Parsed netlist data
        """
        logger.info("Parsing generic netlist format")
        
        # This is a simplified parser for common netlist formats
        # Real implementation would need to handle various formats
        
        lines = content.strip().split('\n')
        current_net = None
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
                
            # Try to detect net definitions
            if line.startswith('NET') or line.startswith('*'):
                # Extract net name
                parts = line.split()
                if len(parts) >= 2:
                    current_net = parts[1].strip('"')
                    if current_net not in self.nets:
                        self.nets[current_net] = []
                        
            # Try to detect component connections
            elif current_net and (' ' in line or '\t' in line):
                parts = line.split()
                if len(parts) >= 2:
                    comp_ref = parts[0]
                    pin = parts[1]
                    
                    self.nets[current_net].append({
                        'component': comp_ref,
                        'pin': pin
                    })
                    
        return self._build_result()
        
    def _build_result(self) -> Dict[str, Any]:
        """Build the final result dictionary.
        
        Returns:
            Result dictionary
        """
        # Calculate statistics
        total_connections = sum(len(pins) for pins in self.nets.values())
        
        # Find power and ground nets
        power_nets = []
        ground_nets = []
        
        for net_name in self.nets.keys():
            net_upper = net_name.upper()
            if any(pwr in net_upper for pwr in ['VCC', 'VDD', '+5V', '+3V3', '+12V', 'PWR']):
                power_nets.append(net_name)
            elif any(gnd in net_upper for gnd in ['GND', 'VSS', '0V', 'GROUND']):
                ground_nets.append(net_name)
                
        return {
            'components': self.components,
            'nets': dict(self.nets),
            'statistics': {
                'component_count': len(self.components),
                'net_count': len(self.nets),
                'total_connections': total_connections,
                'power_nets': power_nets,
                'ground_nets': ground_nets
            }
        }


def extract_netlist_from_schematic(schematic_path: str) -> Dict[str, Any]:
    """Extract netlist information from a KiCad schematic file.
    
    This is a simplified version that extracts basic connectivity info
    from the schematic file directly.
    
    Args:
        schematic_path: Path to .kicad_sch file
        
    Returns:
        Dictionary with netlist information
    """
    logger.info(f"Extracting netlist from schematic: {schematic_path}")
    
    schematic_path = Path(schematic_path)
    if not schematic_path.exists():
        return {"error": "Schematic file not found"}
        
    try:
        with open(schematic_path, 'r') as f:
            content = f.read()
            
        components = {}
        wires = []
        labels = []
        
        # Extract components (simplified)
        symbol_pattern = r'\(symbol[^(]*\(lib_id "([^"]+)"\)[^(]*\(property "Reference" "([^"]+)"[^)]*\)[^(]*\(property "Value" "([^"]+)"'
        
        for match in re.finditer(symbol_pattern, content, re.DOTALL):
            lib_id = match.group(1)
            reference = match.group(2)
            value = match.group(3)
            
            components[reference] = {
                'reference': reference,
                'value': value,
                'lib_id': lib_id,
                'type': lib_id.split(':')[0] if ':' in lib_id else 'unknown'
            }
            
        # Extract wire segments
        wire_pattern = r'\(wire[^(]*\(pts[^(]*\(xy ([\d.-]+) ([\d.-]+)\)[^(]*\(xy ([\d.-]+) ([\d.-]+)\)'
        
        for match in re.finditer(wire_pattern, content):
            wires.append({
                'start': {'x': float(match.group(1)), 'y': float(match.group(2))},
                'end': {'x': float(match.group(3)), 'y': float(match.group(4))}
            })
            
        # Extract labels (net names)
        label_pattern = r'\(label "([^"]+)"[^(]*\(at ([\d.-]+) ([\d.-]+)'
        
        for match in re.finditer(label_pattern, content):
            labels.append({
                'name': match.group(1),
                'position': {'x': float(match.group(2)), 'y': float(match.group(3))}
            })
            
        # Build basic connectivity (simplified - doesn't trace actual connections)
        # In a real implementation, you'd trace wires to find actual connections
        
        return {
            'components': components,
            'statistics': {
                'component_count': len(components),
                'wire_count': len(wires),
                'label_count': len(labels)
            },
            'labels': labels,
            'note': 'This is a simplified extraction. Use KiCad CLI for complete netlist.'
        }
        
    except Exception as e:
        logger.error(f"Error extracting netlist: {e}")
        return {"error": str(e)}


def analyze_connectivity(netlist_data: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze connectivity patterns in netlist data.
    
    Args:
        netlist_data: Parsed netlist data
        
    Returns:
        Connectivity analysis
    """
    if 'error' in netlist_data:
        return netlist_data
        
    analysis = {
        'most_connected_components': [],
        'isolated_components': [],
        'net_fanout': {},
        'component_types': defaultdict(int)
    }
    
    # Count connections per component
    component_connections = defaultdict(int)
    
    for net_name, connections in netlist_data.get('nets', {}).items():
        # Count fanout per net
        analysis['net_fanout'][net_name] = len(connections)
        
        # Count connections per component
        for conn in connections:
            component_connections[conn['component']] += 1
            
    # Find most connected components
    if component_connections:
        sorted_comps = sorted(
            component_connections.items(), 
            key=lambda x: x[1], 
            reverse=True
        )
        analysis['most_connected_components'] = [
            {'component': comp, 'connections': count}
            for comp, count in sorted_comps[:10]
        ]
        
    # Find isolated components
    all_components = set(netlist_data.get('components', {}).keys())
    connected_components = set(component_connections.keys())
    isolated = all_components - connected_components
    analysis['isolated_components'] = list(isolated)
    
    # Analyze component types
    for comp_ref, comp_data in netlist_data.get('components', {}).items():
        # Extract component type from reference
        comp_type = re.match(r'^([A-Za-z]+)', comp_ref)
        if comp_type:
            analysis['component_types'][comp_type.group(1)] += 1
            
    return analysis