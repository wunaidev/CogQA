from fuzzywuzzy import fuzz, process as fuzzy_process
import re
import numpy as np
from bisect import bisect_left
import torch
# from hotpot_evaluate_v1 import normalize_answer, f1_score
# def fuzzy_retrieve(entity, pool):
#     if len(pool) > 100:
#         # fullwiki, exact match
#         # TODO: test ``entity (annotation)'' and find the most like one
#         if pool.get(entity):
#             return entity
#         else:
#             return None
#     else:
#         # distractor mode or use link in original wiki, no need to consider ``entity (annotation)''
#         pool = pool if isinstance(pool, list) else pool.keys()
#         f1max, ret = 0, None
#         for t in pool:
#             f1, precision, recall = f1_score(entity, t)
#             if f1 > f1max:
#                 f1max, ret = f1, t
#         return ret

def fuzzy_retrieve(entity, pool, setting, threshold = 50):
    if setting == 'distractor':
        pool = pool.keys()
    else:
        if not hasattr(fuzzy_retrieve, 'db'):
            from redis import StrictRedis
            fuzzy_retrieve.db = StrictRedis(host='localhost', port=6379, db=0)
        assert isinstance(pool, tuple)
        title, sen_num = pool
        pool = set()
        for i in range(sen_num + 1):
            name = 'edges:###{}###{}'.format(i, title)
            tmp = set([x.decode().split('###')[0] for x in fuzzy_retrieve.db.lrange(name, 0, -1)])
            pool |= tmp
        
    best = (0, -1)
    for item in pool:
        item_refined = re.sub(r' \(.*?\)$', '', item)
        score = fuzz.ratio(item_refined, entity)
        if best[0] < score:
            best = (score, item)
    return best[1] if best[0] > threshold else None

def get_context_fullwiki(title):
    if not hasattr(get_context_fullwiki, 'db'):
        from redis import StrictRedis
        get_context_fullwiki.db = StrictRedis(host='localhost', port=6379, db=0, decode_responses=True)
    return get_context_fullwiki.db.lrange(title, 0, -1)

def dp(a, b): # a source, b long text
    f, start = np.zeros((len(a), len(b))), np.zeros((len(a), len(b)), dtype = np.int)
    for j in range(len(b)):
        f[0, j] = int(a[0] != b[j])
        if j > 0 and b[j - 1].isalnum():
            f[0, j] += 10
        start[0, j] = j
    for i in range(1, len(a)):        
        for j in range(len(b)):
            # (0, i-1) + del(i) ~ (start[j], j)
            f[i, j] = f[i - 1, j] + 1
            start[i, j] = start[i - 1, j]
            if j == 0:
                continue
            if f[i, j] > f[i - 1, j - 1] + int(a[i] != b[j]):
                f[i, j] = f[i - 1, j - 1] + int(a[i] != b[j])
                start[i, j] = start[i-1, j - 1]

            if f[i, j] > f[i, j - 1] + 0.5:
                f[i, j] = f[i, j - 1] + 0.5
                start[i, j] = start[i, j - 1]
#     print(f[len(a) - 1])
    r = np.argmin(f[len(a) - 1])
    ret = [start[len(a) - 1, r], r + 1]
#     print(b[ret[0]:ret[1]])
    score = f[len(a) - 1, r] / len(a)
    return (ret, score)

def fuzzy_find(entities, sentence):
    ret = []
    for entity in entities:
        item = re.sub(r' \(.*?\)$', '', entity).strip()
        if item == '':
            item = entity
            print(item)
        r, score = dp(item, sentence)
        if score < 0.5:
            matched = sentence[r[0]: r[1]].lower()
            final_word = item.split()[-1]
            # from end
            retry = False
            while fuzz.partial_ratio(final_word.lower(), matched) < 80:
                retry = True
                end = len(item) - len(final_word)
                while end > 0 and item[end - 1].isspace():
                    end -= 1
                if end == 0:
                    retry = False
                    score = 1
                    break
                item = item[:end]
                final_word = item.split()[-1]
            if retry:
#                 print(entity + ' ### ' + sentence[r[0]: r[1]] + ' ### ' + item)
                r, score = dp(item, sentence)
                score += 0.1

            if score >= 0.5:
#                 print(entity + ' ### ' + sentence[r[0]: r[1]] + ' ### ' + item)
                continue
            del final_word
            # from start
            retry = False
            first_word = item.split()[0]
            while fuzz.partial_ratio(first_word.lower(), matched) < 80:
                retry = True
                start = len(first_word)
                while start < len(item) and item[start].isspace():
                    start += 1
                if start == len(item):
                    retry = False
                    score = 1
                    break
                item = item[start:]
                first_word = item.split()[0]
            if retry:
#                 print(entity + ' ### ' + sentence[r[0]: r[1]] + ' ### ' + item)
                r, score = dp(item, sentence)
                score = max(score, 1 - ((r[1] - r[0]) / len(entity)))
                score += 0.1
#             if score > 0.5:
#                 print(entity + ' ### ' + sentence[r[0]: r[1]] + ' ### ' + item)
            if score < 0.5:
                if item.isdigit() and sentence[r[0]: r[1]] != item:
                    continue
                ret.append((entity, sentence[r[0]: r[1]], int(r[0]), int(r[1]), score))
    non_intersection = []
    for i in range(len(ret)):
        ok = True
        for j in range(len(ret)):
            if j != i:
                if not (ret[i][2] >= ret[j][3] or ret[j][2] >= ret[i][3]) and ret[j][4] < ret[i][4]:
                    ok = False
                    break
                if ret[i][4] > 0.2 and ret[j][4] < 0.1 and not ret[i][1][0].isupper() and len(ret[i][1].split()) <= 3:
                    ok = False
#                    print(ret[i])
                    break
        if ok:
            non_intersection.append(ret[i][:4])
    return non_intersection


GENERAL_WD = ['is', 'are', 'am', 'was', 'were', 'have', 'has', 'had', 'can', 'could', 
              'shall', 'will', 'should', 'would', 'do', 'does', 'did', 'may', 'might', 'must', 'ought', 'need', 'dare']
GENERAL_WD += [x.capitalize() for x in GENERAL_WD]
GENERAL_WD = re.compile(' |'.join(GENERAL_WD))

def judge_question_type(q : str, G = GENERAL_WD) -> int:
    if q.find(' or ') >= 0:
        return 2 
    elif G.match(q):
        return 1
    else:
        return 0


def warmup_linear(x, warmup=0.002):
    if x < warmup:
        return x/warmup
    return 1.0 - x


def find_start_end_after_tokenized(tokenizer, tokenized_text, spans: ['Obama Care', '2006']):
    end_offset, ret = [], []
    for x in tokenized_text:
        offset = len(x) + (end_offset[-1] if len(end_offset) > 0 else -1)
        end_offset.append(offset)
    text = ''.join(tokenized_text)
    for span in spans:
        t = ''.join(tokenizer.tokenize(span))
        start = text.find(t)
        if start >= 0:
            end = start + len(t) - 1 # include end
        else:
            result = fuzzy_find([t], text)
            if len(result) == 0:    
                result = fuzzy_find([re.sub('[UNK]', '',t)], text)
                assert len(result) > 0
            _, _, start, end = result[0]
            end -= 1
        ret.append((bisect_left(end_offset, start), bisect_left(end_offset, end)))
    return ret
    
def find_start_end_before_tokenized(orig_text, spans: [['Oba', '##ma', 'Care'], ['2006']]):
    ret = []
    # print('orig_text: ', orig_text)
    # print('spans', spans)
    orig_text = orig_text.lower()
    for span_pieces in spans:
        # while len(span_pieces) > 0 and span_pieces[0].startswith('##'):
        #     span_pieces.pop(0)
        if len(span_pieces) == 0:
            ret.append((0, 0))
            continue
        span = re.sub('##', '', ''.join(span_pieces))
        start = orig_text.find(span)
        if start >= 0:
            end = start + len(span) # exclude end
        else:
            result = fuzzy_find([span], orig_text)
            if len(result) == 0 and span.find('[UNK]') > 0:
                span = span.replace('[UNK]', '')
                result = fuzzy_find([span], orig_text)
            if len(result) == 0:
                ret.append((0,0))
                continue
            _, _, start, end = result[0]
        ret.append((start, end))
    return ret

def bundle_part_to_batch(all_bundle, l = None, r = None):
    if l is None:
        l, r = 0, len(all_bundle.ids)
    num_samples = r - l
    max_length = max([len(x) for x in all_bundle.ids[l:r]])
    max_seps = max([len(x) for x in all_bundle.sep_positions[l:r]])    
    ids = torch.zeros((num_samples, max_length), dtype = torch.long)
    sep_positions = torch.zeros((num_samples, max_seps), dtype = torch.long)
    hop_start_weights = torch.zeros((num_samples, max_length))
    hop_end_weights = torch.zeros((num_samples, max_length))
    ans_start_weights = torch.zeros((num_samples, max_length))
    ans_end_weights = torch.zeros((num_samples, max_length))
    segment_ids = torch.zeros((num_samples, max_length), dtype = torch.long)
    input_mask = torch.zeros((num_samples, max_length), dtype = torch.long)
    for i in range(l, r):
        length = len(all_bundle.ids[i])
        sep_num = len(all_bundle.sep_positions[i])
        ids[i - l, :length] = torch.tensor(all_bundle.ids[i], dtype = torch.long)
        sep_positions[i - l, :sep_num] = torch.tensor(all_bundle.sep_positions[i])
        hop_start_weights[i - l, :length] = torch.tensor(all_bundle.hop_start_weights[i])
        hop_end_weights[i - l, :length] = torch.tensor(all_bundle.hop_end_weights[i])
        ans_start_weights[i - l, :length] = torch.tensor(all_bundle.ans_start_weights[i])
        ans_end_weights[i - l, :length] = torch.tensor(all_bundle.ans_end_weights[i])
        segment_ids[i - l, :length] = torch.tensor(all_bundle.segment_ids[i], dtype = torch.long)
        input_mask[i - l, :length] = 1
    return ids, segment_ids, input_mask, sep_positions, hop_start_weights, hop_end_weights, ans_start_weights, ans_end_weights

class WindowMean:
    def __init__(self, window_size = 50):
        self.array = []
        self.sum = 0
        self.window_size = window_size
    def update(self, x):
        self.array.append(x)
        self.sum += x
        if len(self.array) > self.window_size:
            self.sum -= self.array.pop(0)
        return self.sum / len(self.array)
