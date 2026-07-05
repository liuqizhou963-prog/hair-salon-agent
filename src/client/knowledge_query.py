"""知识\u5e93\u67e5\u8be2\uff08RAG\uff09- \u53d1\u578b\u5e08\u4fe1\u606f + \u53ef\u7528\u65f6\u95f4\u69fd"""

from loguru import logger
from typing import List, Dict, Any
import json

from src.database.connection import SessionLocal
from src.database.service import StylistService, TimeSlotService

class RAGRetriever:
    """RAG\u77e5\u8bc6\u5e93\u68c0\u7d22\uff08\u7f8e\u53d1\u7279\u5b9a\u4fe1\u606f\uff09"""
    
    def __init__(self):
        """初\u59cb\u5316\u77e5\u8bc6\u5e93"""
        self.knowledge_base = self._load_knowledge_base()
    
    def _load_knowledge_base(self) -> List[Dict[str, str]]:
        """加\u8f7d\u77e5\u8bc6\u5e93\uff08\u7f8e\u53d1\u62a4\u7406\u77e5\u8bc6\uff09"""
        knowledge = [
            {
                "title": "\u70eb\u67d3\u62a4\u7406",
                "content": "\u70eb\u67d3\u540e\u9700\u8981\u4e00\u5468\u5185\u907f\u514d\u6d17\u5934\uff0c\u5efa\u8bae\u4f7f\u7528\u62a4\u8272\u6d17\u53d1\u6c34\u3002\u6bcf\u5468\u505a\u4e00\u6b21\u6df1\u5c42\u62a4\u7406\uff0c\u53ef\u7528\u62a4\u8272\u53d1\u819c\u6216\u8425\u517b\u6cb9\u3002",
                "category": "\u62a4\u7406"
            },
            {
                "title": "\u6bdb\u8e81\u5934\u53d1\u62a4\u7406",
                "content": "\u6bdb\u8e81\u901a\u5e38\u7531\u5e72\u67af\u5f15\u8d77\u3002\u5efa\u8bae\uff1a1. \u5b9a\u671f\u505a\u6df1\u5c42\u62a4\u7406\uff082\u5468\u4e00\u6b21\uff09 2. \u4f7f\u7528\u62a4\u7406\u7cbe\u6cb9 3. \u907f\u514d\u9891\u7e41\u70eb\u67d3 4. \u5439\u5e72\u524d\u7528\u62a4\u7406\u55b7\u96fe",
                "category": "\u62a4\u7406"
            },
            {
                "title": "\u53d1\u8272\u7ef4\u62a4",
                "content": "\u6f02\u67d3\u540e\u7684\u5934\u53d1\u9700\u8981\u7279\u522b\u62a4\u7406\u3002\u5efa\u8bae\u4f7f\u7528\u7d2b\u8272\u6d17\u53d1\u6c34\u7ef4\u62a4\u8272\u6cfd\uff0c\u4e00\u4e2a\u6708\u6765\u5e97\u62a4\u7406\u4e00\u6b21\uff0c\u907f\u514d\u9633\u5149\u66b4\u6652\u3002",
                "category": "\u62a4\u7406"
            },
            {
                "title": "\u70eb\u578b\u4fdd\u6301",
                "content": "\u70eb\u5377\u4fdd\u63017-10\u5929\u6700\u4f73\u3002\u5efa\u8bae\uff1a\u70eb\u540e48\u5c0f\u65f6\u4e0d\u6d17\u5934\uff0c\u4f7f\u7528\u5377\u5ea6\u5b9a\u578b\u55b7\u96fe\uff0c\u6bcf\u6b21\u6d17\u5934\u7528\u6e29\u6c34\uff0c\u5439\u5e72\u65f6\u987a\u7740\u5377\u5ea6\u5439\u3002",
                "category": "\u62a4\u7406"
            },
            {
                "title": "\u5934\u76ae\u62a4\u7406",
                "content": "\u5065\u5eb7\u7684\u5934\u76ae\u662f\u597d\u5934\u53d1\u7684\u57fa\u7840\u3002\u5efa\u8bae\u5b9a\u671f\u505a\u5934\u76ae\u6e05\u6d01\u62a4\u7406\uff0c\u4f7f\u7528\u9002\u5408\u81ea\u5df1\u5934\u76ae\u7684\u6d17\u53d1\u6c34\uff0c\u907f\u514d\u8fc7\u5ea6\u70eb\u67d3\u3002",
                "category": "\u62a4\u7406"
            },
            {
                "title": "\u9632\u6652\u4ea7\u54c1\u63a8\u8350",
                "content": "\u708e\u70ed\u5b63\u8282\u5efa\u8bae\u4f7f\u7528\u542bUV\u9632\u62a4\u7684\u62a4\u7406\u4ea7\u54c1\u3002\u6211\u4eec\u6709\u9632\u6652\u55b7\u96fe\u3001\u62a4\u7406\u6cb9\u7b49\u591a\u79cd\u9009\u62e9\uff0c\u53ef\u6709\u6548\u4fdd\u62a4\u5934\u53d1\u8272\u6cfd\u3002",
                "category": "\u4ea7\u54c1"
            }
        ]
        logger.info(f"\u2705 \u52a0\u8f7d {len(knowledge)} \u6761\u77e5\u8bc6")
        return knowledge
    
    def search(self, query: str, k: int = 3) -> List[Dict[str, str]]:
        """
        \u7b80\u5355\u7684\u5173\u952e\u8bcd\u5339\u914d\u68c0\u7d22
        
        Args:
            query: \u67e5\u8be2\u6587\u672c
            k: \u8fd4\u56de\u6761\u6570
        
        Returns:
            \u68c0\u7d22\u7ed3\u679c
        """
        logger.info(f"\ud83d\udd0d RAG\u68c0\u7d22: {query}")
        
        # \u5173\u952e\u8bcd\u5339\u914d
        query_lower = query.lower()
        results = []
        
        for item in self.knowledge_base:
            title_lower = item["title"].lower()
            content_lower = item["content"].lower()
            
            # \u8ba1\u7b97\u5339\u914d\u5206\u6570
            score = 0
            if query_lower in title_lower:
                score += 10
            if query_lower in content_lower:
                score += 5
            
            # \u5206\u7c7b\u5339\u914d
            if "\u62a4\u7406" in query_lower and item["category"] == "\u62a4\u7406":
                score += 3
            if "\u4ea7\u54c1" in query_lower and item["category"] == "\u4ea7\u54c1":
                score += 3
            
            if score > 0:
                results.append((item, score))
        
        # \u6392\u5e8f\u5e76\u8fd4\u56deTop K
        results.sort(key=lambda x: x[1], reverse=True)
        retrieved = [item for item, score in results[:k]]
        
        logger.info(f"\u2705 \u68c0\u7d22\u5230 {len(retrieved)} \u6761\u7ed3\u679c")
        return retrieved
    
    def search_stylists_and_availability(self, service_type: str) -> Dict[str, Any]:
        """
        \u7ee7\u7ec7\u67e5\u8be2\uff1a\u77e5\u8bc6\u5e93 + \u53d1\u578b\u5e08 + \u53ef\u7528\u65f6\u95f4\u69fd
        \n        \u8fd9\u662f\u6574\u4e2a\u7cfb\u7edf\u7684\u4e00\u4e2a\u6838\u5fc3\u63a5\u53e3\uff1a
        1. RAG \u67e5\u627e\u76f8\u5173\u77e5\u8bc6
        2. \u4ece PostgreSQL \u67e5\u627e\u64cd\u957f\u53d1\u578b\u7684\u53d1\u578b\u5e08
        3. \u4ece PostgreSQL \u67e5\u627e\u53d1\u578b\u5e08\u7684\u53ef\u7528\u65f6\u95f4\u69fd
        """
        logger.info(f"\ud83d\udd0d \u7ee7\u7ec7\u67e5\u8be2: {service_type}")
        
        db = SessionLocal()
        try:
            # 1. RAG \u77e5\u8bc6
            knowledge = self.search(f"{service_type}\u62a4\u7406", k=3)
            
            # 2. \u67e5\u627e\u64cd\u957f\u53d1\u578b
            stylists = StylistService.search_stylists_by_specialty(db, service_type)
            
            # 3. \u4e3a\u6bcf\u4e2a\u53d1\u578b\u5e08\u6dfb\u52a0\u53ef\u7528\u65f6\u95f4\u69fd
            stylists_with_slots = []
            for stylist in stylists:
                slots = TimeSlotService.get_available_slots(db, str(stylist.id), days_ahead=7)
                stylists_with_slots.append({
                    "stylist_id": str(stylist.id),
                    "name": stylist.user.name,
                    "specialty": stylist.specialty,
                    "experience_years": stylist.experience_years,
                    "rating": stylist.rating,
                    "available_slots": slots
                })
            
            logger.info(f"\u2705 \u67e5\u8be2\u5b8c\u6210: {len(knowledge)} \u6761\u77e5\u8bc6, {len(stylists_with_slots)} \u4e2a\u53d1\u578b\u5e08")
            
            return {
                "service_type": service_type,
                "knowledge": knowledge,
                "stylists": stylists_with_slots,
                "total_stylists": len(stylists_with_slots)
            }
        finally:
            db.close()

# \u5168\u5c40 RAG \u68c0\u7d22\u5b9e\u4f8b
rag_retriever = RAGRetriever()
