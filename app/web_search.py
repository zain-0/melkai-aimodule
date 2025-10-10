import re
from typing import List, Dict
from ddgs import DDGS
import logging

logger = logging.getLogger(__name__)


class WebSearcher:
    """Web search functionality prioritizing .gov domains"""
    
    def __init__(self):
        self.ddgs = DDGS()
    
    def search_gov_laws(
        self, 
        query: str, 
        location: Dict[str, str], 
        max_results: int = 10
    ) -> List[Dict[str, str]]:
        """
        Search for government laws and regulations
        
        Args:
            query: Search query (e.g., "landlord tenant security deposit")
            location: Dict with city, state, county info
            max_results: Maximum number of results to return
            
        Returns:
            List of search results with title, url, snippet
        """
        # Build location-specific query
        location_parts = []
        if location.get("city"):
            location_parts.append(location["city"])
        if location.get("county"):
            location_parts.append(f"{location['county']} county")
        if location.get("state"):
            location_parts.append(location["state"])
        
        location_str = " ".join(location_parts)
        
        # Prioritize .gov sites
        search_query = f"{query} {location_str} site:.gov"
        
        logger.info(f"Searching: {search_query}")
        
        results = []
        try:
            # DuckDuckGo search
            search_results = self.ddgs.text(
                search_query,
                max_results=max_results
            )
            
            for result in search_results:
                results.append({
                    "title": result.get("title", ""),
                    "url": result.get("href", ""),
                    "snippet": result.get("body", ""),
                    "is_gov": self._is_gov_site(result.get("href", ""))
                })
            
            # If we didn't get enough .gov results, try broader search
            gov_results = [r for r in results if r["is_gov"]]
            if len(gov_results) < 3:
                broader_query = f"{query} {location_str} landlord tenant law"
                broader_results = self.ddgs.text(
                    broader_query,
                    max_results=max_results
                )
                
                for result in broader_results:
                    url = result.get("href", "")
                    if url not in [r["url"] for r in results]:
                        results.append({
                            "title": result.get("title", ""),
                            "url": url,
                            "snippet": result.get("body", ""),
                            "is_gov": self._is_gov_site(url)
                        })
        
        except Exception as e:
            logger.error(f"Search error: {str(e)}")
        
        # Sort by .gov priority (.gov sites first, then maintain original order)
        gov_results = [r for r in results if r["is_gov"]]
        non_gov_results = [r for r in results if not r["is_gov"]]
        results = gov_results + non_gov_results
        
        return results[:max_results]
    
    def search_multiple_topics(
        self,
        topics: List[str],
        location: Dict[str, str],
        max_results_per_topic: int = 5
    ) -> Dict[str, List[Dict[str, str]]]:
        """
        Search for multiple legal topics
        
        Args:
            topics: List of topics to search (e.g., ["security deposit", "eviction notice"])
            location: Location information
            max_results_per_topic: Results per topic
            
        Returns:
            Dict mapping topic to search results
        """
        results = {}
        
        for topic in topics:
            results[topic] = self.search_gov_laws(
                topic,
                location,
                max_results=max_results_per_topic
            )
        
        return results
    
    @staticmethod
    def _is_gov_site(url: str) -> bool:
        """Check if URL is a government website"""
        gov_patterns = [
            r"\.gov(/|$)",
            r"\.gov\.",
        ]
        
        for pattern in gov_patterns:
            if re.search(pattern, url, re.IGNORECASE):
                return True
        
        return False
    
    @staticmethod
    def extract_legal_topics(lease_text: str) -> List[str]:
        """
        Extract potential legal topics from lease text for targeted searching
        
        Args:
            lease_text: Full text of the lease
            
        Returns:
            List of legal topics to search for
        """
        topics = set()
        
        # Common lease topics that may have regulations
        topic_keywords = {
            "security deposit": ["security deposit", "deposit"],
            "eviction": ["eviction", "termination", "notice to vacate"],
            "repairs and maintenance": ["repair", "maintenance", "habitability"],
            "rent increase": ["rent increase", "rent adjustment"],
            "late fees": ["late fee", "late charge", "late payment"],
            "pet policy": ["pet", "animal"],
            "subletting": ["sublease", "sublet", "assignment"],
            "entry and access": ["entry", "access", "inspection"],
            "utilities": ["utilities", "water", "electric", "gas"],
            "lease termination": ["termination", "breaking lease", "early termination"],
        }
        
        lease_lower = lease_text.lower()
        
        for topic, keywords in topic_keywords.items():
            if any(keyword in lease_lower for keyword in keywords):
                topics.add(topic)
        
        # Always search for general landlord-tenant law
        topics.add("landlord tenant law")
        
        return list(topics)
