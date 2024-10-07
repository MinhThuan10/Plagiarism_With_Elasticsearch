import sys
import os
# Thêm đường dẫn của thư mục cha vào sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from processing import *
import time
import pymupdf  # import package PyMuPDF
import io
from sentence_split import *
import warnings
from urllib3.exceptions import InsecureRequestWarning
from pymongo import MongoClient
# Tắt cảnh báo InsecureRequestWarning
warnings.simplefilter('ignore', InsecureRequestWarning)
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from bson import Binary
from highlight import *
# Kết nối tới MongoDB
client = MongoClient('mongodb://localhost:27017/')
db = client['Plagiarism_PDF']
collection_sentences = db['sentences']
collection_files = db['files']

# Start the timer
start_time = time.time()
plagiarized_count = 0
file_path = './test/Data/loicamon.pdf'

assignment_id = 1
file_id = 2
title = 'loicamon'
author = 'Thuan'


def read_pdf_binary(file_path):
    with open(file_path, 'rb') as file:
        return file.read()

def save_pdf_to_mongo(pdf_path):
    content = read_pdf_binary(pdf_path)
    result = {
        "assignment_id" : assignment_id,
        "file_id": file_id,
        "title": title,
        "author": author,
        "content": Binary(content),
        "type": 'raw'
        }
    collection_files.insert_one(result)
save_pdf_to_mongo(file_path)

def is_within(qua_t, qua_s):
    if (qua_t[0].x >= qua_s[0].x and qua_t[0].y == qua_s[0].y and qua_t[-1].x <= qua_s[-1].x and qua_t[-1].y == qua_s[-1].y):
        return True
    else:
        return False
    
def is_position(new_position, positions):
    merged = False

    for position in positions:
        if (new_position['y_0'] == position['y_0'] and new_position['y_1'] == position['y_1']):
            if (new_position['x_0'] <= position['x_0'] and new_position['x_1'] >= position['x_1'] - 5):
                position['x_0'] = new_position['x_0']
                position['x_1'] = new_position['x_1']
                merged = True
                break
            if (new_position['x_0'] <= position['x_0'] and new_position['x_1'] >= position['x_0']): #1
                position['x_0'] = new_position['x_0']
                merged = True
                break     
            if (new_position['x_0'] >= position['x_0'] and new_position['x_1'] <= position['x_1']): #2
                merged = True
                break
            if (new_position['x_0'] >= position['x_0'] and new_position['x_0'] <= position['x_1'] + 5): #3
                position['x_1'] = new_position['x_1']
                merged = True
                break     
    return merged
def should_merge(pos1, pos2):
    # Check if positions overlap or are adjacent on the x-axis
    return not (pos1["x_1"] < pos2["x_0"] or pos1["x_0"] > pos2["x_1"])


pdf_document = fitz.open(file_path)
doc = pymupdf.open(file_path)
current_school_id = 0
school_cache = {}
sentences_cache = {}
word_count = 0
word_count_similarity = 0
sentence_index = 0
references = False
for page_num in range(pdf_document.page_count):
    page = pdf_document[page_num]
    text = page.get_text("text")
    sentences = split_sentences(text)
    sentences = remove_sentences(sentences)
    print(sentences)

    if "TÀI LIỆU THAM KHẢO" in sentences[0].upper():
        references = True
    for sentence in sentences:
        print(sentence)
        quotation_marks = check_type_setence(sentence)
        word_count += len(sentence.split())
        preprocessed_query, sentence_results = search_sentence_elastic(sentence)
        sources = []
        if preprocessed_query is None:
            print("Sentence Error")
            if references == False:
                result = {
                    "file_id": file_id,
                    "title": title,
                    "page": page_num,
                    "sentence_index": sentence_index,
                    "sentence": sentence,
                    "references": "no",
                    "quotation_marks": quotation_marks,
                    "sources": []
                }
                collection_sentences.insert_one(result)
            else:
                result = {
                    "file_id": file_id,
                    "title": title,
                    "page": page_num,
                    "sentence_index": sentence_index,
                    "sentence": sentence,
                    "references": "yes",
                    "quotation_marks": quotation_marks,
                    "sources": []
                }
                collection_sentences.insert_one(result)
            sentence_index = sentence_index + 1
            
            continue
        if sentence_results:
            print("So sánh trong dữ liệu")
            preprocessed_references = [preprocess_text_vietnamese(ref['sentence'])[0] for ref in sentence_results]
            all_sentences = [preprocessed_query] + preprocessed_references

            # Tính toán embeddings cho tất cả các câu cùng một lúc
            embeddings = embedding_vietnamese(all_sentences)
            query_embedding = embeddings[0].reshape(1, -1)
            reference_embeddings = embeddings[1:]
            similarity_scores = calculate_similarity(query_embedding, reference_embeddings)

            query_length = len(preprocessed_query.split())
            dynamic_threshold = calculate_dynamic_threshold(query_length)
            max_score = 0
            word_count_max = 0
            source_id = 0
            for idx, score in enumerate(similarity_scores[0]):
                if score >= dynamic_threshold:
                    school_name = sentence_results[idx]['school_name']
                    file_id_source = sentence_results[idx]['file_name']
                    best_match = sentence_results[idx]['sentence']
                    type = sentence_results[idx]['type']
                    
                    if school_name in school_cache:
                        school_id = school_cache[school_name]
                    else:
                        school_id = current_school_id
                        school_cache[school_name] = school_id
                        current_school_id += 1
                    positions = []
                    word_count_sml,paragraphs_best_math, paragraphs  = common_ordered_words(best_match, sentence)
                    quads_sentence = page.search_for(sentence, quads=True)
                    
                    for paragraph in paragraphs:
                        quads_token = page.search_for(paragraph, quads=True)
                        for qua_s in quads_sentence:
                            for qua_t in quads_token:
                                if is_within(qua_t, qua_s) == True:
                                    new_position = {
                                    "x_0" : qua_t[0].x,
                                    "y_0" : qua_t[0].y,
                                    "x_1" : qua_t[-1].x,
                                    "y_1" : qua_t[-1].y,
                                    }
                            
                                    merged = is_position(new_position, positions)
                                    if not merged:
                                        positions.append(new_position)    
                                        
                                           
                                        
                    best_match = wrap_paragraphs_with_color(paragraphs_best_math, best_match, school_id)
                    sources.append({
                        "source_id":source_id,
                        "school_id": school_id,
                        "school_name": school_name,
                        "file_id": file_id_source,
                        "type_source": type, 
                        "except": 'no',
                        "color": color_hex[school_id],
                        "school_stt": 0,
                        "best_match": best_match,
                        "score": float(score),
                        "highlight": {
                            "word_count_sml": word_count_sml,
                            "paragraphs": paragraphs_best_math,
                            "position": positions
                        }
                    })
                    source_id = source_id+1
                    if score > max_score:
                        max_score = score
                        word_count_max = word_count_sml
            

        result = search_google(preprocessed_query)
        items = result.get('items', [])
        all_snippets = [item.get('snippet', '') for item in items if item.get('snippet', '')]
        
        if not all_snippets:
            print("No on Internet")
            continue

        top_similarities = compare_sentences(sentence, all_snippets)
        for _, idx in top_similarities:
            url = items[idx].get('link')
            print(url)
            snippet = all_snippets[idx]
            # Tìm trong cache trước khi tải nội dung
            sentences = sentences_cache.get(url)
                
            if sentences is None:
                content = fetch_url(url)
                sentences_from_webpage = split_sentences(content)
                sentences = remove_sentences(sentences_from_webpage)
                sentences_cache[url] = sentences

            if sentences:             
                snippet_parts = split_snippet(snippet)
                # snippet_parts = remove_snippet_parts(snippet_parts)
                # Lọc các câu chứa ít nhất một phần của snippet
                relevant_sentences = [s for s in sentences if check_snippet_in_sentence(s, snippet_parts)]
                if relevant_sentences:
                    similarity_sentence, match_sentence, _ = compare_with_sentences(sentence, relevant_sentences)
                    if similarity_sentence > dynamic_threshold:
                        parsed_url = urlparse(url)
                        # Lấy tên miền chính
                        domain = parsed_url.netloc.replace('www.', '')
                        school_name = domain
                        # Logic gán school_id
                        if school_name in school_cache:
                            school_id = school_cache[school_name]
                        else:
                            school_id = current_school_id
                            school_cache[school_name] = school_id
                            current_school_id += 1

                        file_id_source = url
                        file_name = items[idx].get('title')
                        best_match = match_sentence

                        positions = []
                        word_count_sml, paragraphs_best_math, paragraphs = common_ordered_words(best_match, sentence)
                        quads_sentence = page.search_for(sentence, quads=True)
                        
                        for paragraph in paragraphs:
                            quads_token = page.search_for(paragraph, quads=True)
                            for qua_s in quads_sentence:
                                for qua_t in quads_token:
                                    if is_within(qua_t, qua_s) == True:
                                        new_position = {
                                        "x_0" : qua_t[0].x,
                                        "y_0" : qua_t[0].y,
                                        "x_1" : qua_t[-1].x,
                                        "y_1" : qua_t[-1].y,
                                        }                                    
                                        if positions:
                                            merged = is_position(new_position, positions)
                                            if not merged:
                                                positions.append(new_position) 
                                        else:
                                            positions.append(new_position) 

                                    
                        best_match = wrap_paragraphs_with_color(paragraphs_best_math, best_match, school_id)
                        sources.append({
                            "source_id": source_id,
                            "school_id": school_id,
                            "school_name": domain,
                            "file_id": file_id_source,
                            "type_source": "Internet",
                            "except": 'no',
                            "color": color_hex[school_id],
                            "school_stt": 0,
                            "best_match": best_match,
                            "score": float(similarity_sentence),
                            "highlight": {
                                "word_count_sml": word_count_sml,
                                "paragraphs": paragraphs_best_math,
                                "position": positions
                            }
                        })
                        source_id = source_id +1

                        if score > max_score:
                            max_score = score
                            word_count_max = word_count_sml

        if sources:
            if references == False:
                result = {
                    "file_id": file_id,
                    "title": title,
                    "page": page_num,
                    "sentence_index": sentence_index,
                    "sentence": sentence,
                    "references": "no",
                    "quotation_marks": quotation_marks,
                    "sources": sources
                }
                collection_sentences.insert_one(result)
            else:
                result = {
                    "file_id": file_id,
                    "title": title,
                    "page": page_num,
                    "sentence_index": sentence_index,
                    "sentence": sentence,
                    "references": "yes",
                    "quotation_marks": quotation_marks,
                    "sources": sources
                }
                collection_sentences.insert_one(result)
            plagiarized_count +=1
            
        else:
            if references == False:
                result = {
                    "file_id": file_id,
                    "title": title,
                    "page": page_num,
                    "sentence_index": sentence_index,
                    "sentence": sentence,
                    "references": "no",
                    "quotation_marks": quotation_marks,
                    "sources": []
                }
                collection_sentences.insert_one(result)
            else:
                result = {
                    "file_id": file_id,
                    "title": title,
                    "page": page_num,
                    "sentence_index": sentence_index,
                    "sentence": sentence,
                    "references": "yes",
                    "quotation_marks": quotation_marks,
                    "sources": []
                }
                collection_sentences.insert_one(result)
        
        word_count_similarity += word_count_max
        sentence_index = sentence_index + 1

num_threads = os.cpu_count()

sentences_data = list(collection_sentences.find({"file_id": int(file_id), "sources": {"$ne": None, "$ne": []}}))
school_sources = {}
for sentence in sentences_data:
    sources = sentence.get('sources', [])
    if sources:
        best_source = max(sources, key=lambda x: x['score'])
        school_id = best_source['school_id']
        highlight_ = best_source['highlight']
        if school_id not in school_sources:
            school_sources[school_id] = {
                "word_count": 0
            }
        school_sources[school_id]['word_count'] += highlight_.get('word_count_sml', 0)

school_sources = sorted(school_sources.items(), key=lambda x: x[1]['word_count'], reverse=True)

for i, (school_id_source, _)in enumerate(school_sources):
    for sentence in sentences_data:
        sources = sentence.get('sources', [])
        for source in sources:
            school_id = source['school_id']
            if school_id == school_id_source:
                collection_sentences.update_one(
                    {"_id": sentence["_id"], "sources.school_id": school_id},
                    {"$set": {"sources.$.school_stt": i + 1}}
                )

file_highlighted = highlight(file_id, ["student_Data", "Internet", "Ấn bản"])

if file_highlighted is not None:
    # Tạo một đối tượng BytesIO để lưu file PDF đã chỉnh sửa
    pdf_output_stream = io.BytesIO()
    
    # Lưu PDF từ đối tượng fitz.Document vào BytesIO
    file_highlighted.save(pdf_output_stream)
    file_highlighted.close()

    # Lưu thông tin vào MongoDB với PDF đã chỉnh sửa
    result = {
        "assignment_id": assignment_id,
        "file_id": file_id,
        "title": title,
        "author": author,
        "page_count": pdf_document.page_count,
        "word_count": word_count,
        "plagiarism": word_count_similarity / word_count * 100,
        "content": Binary(pdf_output_stream.getvalue()),  # Lưu PDF dưới dạng Binary
        "type": 'checked',
        "source":{
            "student_data": "checked",
            "internet": "checked",
            "paper": "checked"
        },
        "fillter":{
            "references": "",
            "quotation_marks": ""
        }
    }
    
    # Chèn dữ liệu vào MongoDB
    collection_files.insert_one(result)

# 
    content = read_pdf_binary(file_path)
    result = {
        "assignment_id" : assignment_id,
        "file_id": file_id,
        "title": title,
        "author": author,
        "page_count": pdf_document.page_count,
        "word_count": word_count,
        "content": Binary(content),
        "type": 'view_all'
        }
    collection_files.insert_one(result)




# End the timer
end_time = time.time()
# Calculate the elapsed time
elapsed_time = end_time - start_time
print(f"Thời gian thực hiện: {elapsed_time:.2f} giây")
print(f"Số lượng câu phát hiện đạo văn: {plagiarized_count}")
print(f"Phần trăm đạo văn:{word_count_similarity/word_count*100}%")