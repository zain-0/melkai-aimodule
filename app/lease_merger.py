"""
Merge and deduplication logic for window results
"""
import hashlib
import json
import logging
from typing import List, Dict, Any, Tuple, Optional
from collections import Counter

logger = logging.getLogger(__name__)


class LeaseResultMerger:
    """Merge and deduplicate extraction results from multiple windows"""
    
    def __init__(self):
        self.conflicts = []
    
    def merge_results(self, window_results: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], List[str]]:
        """Merge results from all windows with conflict detection"""
        logger.info(f"Merging {len(window_results)} window results")
        self.conflicts = []
        
        merged = {
            'utility_responsibilities': [],
            'common_area_maintenance': [],
            'additional_fees': [],
            'tenant_improvements': [],
            'term': None,
            'rent_and_deposits': None,
            'other_deposits': [],
            'rent_increase_schedule': [],
            'abatements_discounts': [],
            'special_clauses': [],
            'nsf_fees': None
        }
        
        # Merge array fields with deduplication
        array_fields = [
            'utility_responsibilities',
            'common_area_maintenance',
            'additional_fees',
            'tenant_improvements',
            'other_deposits',
            'rent_increase_schedule',
            'abatements_discounts',
            'special_clauses'
        ]
        
        for field in array_fields:
            merged[field] = self._merge_array_field(field, window_results)
        
        # Merge single object fields
        merged['term'] = self._merge_single_object('term', window_results)
        merged['rent_and_deposits'] = self._merge_single_object('rent_and_deposits', window_results)
        merged['nsf_fees'] = self._merge_single_object('nsf_fees', window_results)
        
        logger.info(f"Merge complete. Found {len(self.conflicts)} conflicts")
        
        return merged, self.conflicts
    
    def _calculate_hash(self, obj: Any) -> str:
        """Calculate content hash for deduplication"""
        normalized = json.dumps(obj, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(normalized.encode()).hexdigest()
    
    def _merge_array_field(self, field_name: str, window_results: List[Dict[str, Any]]) -> List[Dict]:
        """Merge array field with deduplication"""
        all_items = []
        
        # Collect all items from all windows
        for window_result in window_results:
            data = window_result.get('data', {})
            items = data.get(field_name, [])
            if items:
                all_items.extend(items)
        
        if not all_items:
            return []
        
        # Deduplicate by content hash
        seen_hashes = {}
        for item in all_items:
            item_hash = self._calculate_hash(item)
            if item_hash not in seen_hashes:
                seen_hashes[item_hash] = {'item': item, 'count': 1}
            else:
                seen_hashes[item_hash]['count'] += 1
        
        # Return unique items (sorted by frequency)
        unique_items = [entry['item'] for entry in 
                       sorted(seen_hashes.values(), key=lambda x: x['count'], reverse=True)]
        
        logger.debug(f"Merged {field_name}: {len(all_items)} total → {len(unique_items)} unique")
        return unique_items
    
    def _merge_single_object(self, field_name: str, window_results: List[Dict[str, Any]]) -> Optional[Dict]:
        """Merge single object field with conflict detection"""
        all_values = []
        
        # Collect all non-null values
        for window_result in window_results:
            data = window_result.get('data', {})
            value = data.get(field_name)
            if value:
                all_values.append(value)
        
        if not all_values:
            return None
        
        # If only one value, return it
        if len(all_values) == 1:
            return all_values[0]
        
        # Multiple values - need to merge by field
        merged_obj = {}
        all_keys = set()
        for obj in all_values:
            all_keys.update(obj.keys())
        
        for key in all_keys:
            field_values = [obj.get(key) for obj in all_values if obj.get(key) is not None]
            
            if not field_values:
                merged_obj[key] = None
            elif len(set(json.dumps(v, sort_keys=True) for v in field_values)) == 1:
                # All values are the same
                merged_obj[key] = field_values[0]
            else:
                # Conflict - use most common value
                value_counts = Counter(json.dumps(v, sort_keys=True) for v in field_values)
                most_common_json = value_counts.most_common(1)[0][0]
                merged_obj[key] = json.loads(most_common_json)
                
                # Log conflict
                conflict_msg = f"{field_name}.{key}: Multiple values found - {value_counts}"
                self.conflicts.append(conflict_msg)
                logger.warning(conflict_msg)
        
        return merged_obj
    
    def calculate_confidence_scores(self, window_results: List[Dict[str, Any]]) -> Dict[str, float]:
        """Calculate confidence scores based on consistency across windows"""
        # Simple implementation - can be enhanced
        total_windows = len(window_results)
        if total_windows == 0:
            return {}
        
        return {
            'overall_confidence': 1.0 if len(self.conflicts) == 0 else 0.8,
            'data_consistency': max(0.0, 1.0 - (len(self.conflicts) / 10))
        }
    
    def validate_merged_data(self, merged_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Basic validation of merged data"""
        issues = []
        
        # Check for required fields
        if not merged_data.get('term'):
            issues.append("Missing term information")
        
        if not merged_data.get('rent_and_deposits'):
            issues.append("Missing rent and deposits information")
        
        return len(issues) == 0, issues


def merge_window_results(window_results: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Main entry point for merging window results"""
    merger = LeaseResultMerger()
    merged_data, conflicts = merger.merge_results(window_results)
    confidence_scores = merger.calculate_confidence_scores(window_results)
    is_valid, issues = merger.validate_merged_data(merged_data)
    
    merge_metadata = {
        'conflicts_found': len(conflicts) > 0,
        'conflict_details': conflicts,
        'confidence_scores': confidence_scores,
        'validation_passed': is_valid,
        'validation_issues': issues
    }
    return merged_data, merge_metadata
