# python Libraries

# basic
import os
import re
import sys
import csv
import time
import json
import urllib
import pickle
import argparse

import warnings
warnings.filterwarnings("ignore")

reload(sys)
sys.setdefaultencoding('utf-8')

# NLTK
import string
from nltk.corpus import stopwords
from nltk.stem import WordNetLemmatizer

# trational Classifier
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier

# deep Classifier
import torch
from PIL import *
import torchvision
import torch.nn as nn
from torchvision import datasets, models, transforms
from torch.autograd import Variable

# self-defined
import _cmu_tagger
import _score_calculator as sc


class ResNet18(nn.Module):
    def __init__(self):
        super(ResNet18, self).__init__()
        self.resnet = models.resnet18(pretrained=True)
        
        self.resnet.fc = nn.Linear(512, 3)

    def forward(self, x):
        x = self.resnet(x)
        return x


def process_raw_tweets(tweet_raw_lines):

    tweet_text_lines = tweet_raw_lines

    # Remove Retweet Tags
    tweet_text_lines = [' '.join(re.sub("(RT @\S+)", " ", tweet_text_line).split()) for tweet_text_line in tweet_text_lines]

    # Remove Mentions
    tweet_text_lines = [' '.join(re.sub("(@\S+)", " ", tweet_text_line).split()) for tweet_text_line in tweet_text_lines]

    # Remove URLs
    tweet_text_lines = [' '.join(re.sub("(https?:\/\/t\.co\S*)", " ", tweet_text_line).split()) for tweet_text_line in tweet_text_lines]

    # Extract Taggers
    tweet_tagger_lines = _cmu_tagger.runtagger_parse(tweet_text_lines, run_tagger_cmd="java -XX:ParallelGCThreads=2 -Xmx500m -jar lib/ark-tweet-nlp-0.3.2.jar")

    # Filter out Taggers + Remove Stopwords + Remove Keywords + Format words + Lemmatization + Lowercase
    tweet_processed = []

    stop_words = set(stopwords.words('english'))

    wordnet_lemmatizer = WordNetLemmatizer()

    for tweet_tagger_line in tweet_tagger_lines:

        tweet_tagger_processed = []

        for tweet_tagger in tweet_tagger_line:
            if tweet_tagger[1] in ['N', 'V', 'A', 'E', 'R', '#']:
                tagger = str(tweet_tagger[0]).lower().decode('utf-8').strip(string.punctuation)
                if tagger not in stop_words:
                    if tweet_tagger[1] == 'V':
                        tagger_lem = wordnet_lemmatizer.lemmatize(tagger, 'v')
                    else:
                        tagger_lem = wordnet_lemmatizer.lemmatize(tagger)
                    if len(tagger_lem) > 3:
                        tweet_tagger_processed.append(tagger_lem)

        tweet_tagger_processed = ' '.join(tweet_tagger_processed)

        tweet_processed.append(tweet_tagger_processed)

    # Remove Duplicates
    tweet_processed = list(set(tweet_processed))

    return tweet_processed


def user_info_crawler(screen_name, user_dir, user_profile_f, user_profileimg_f, user_tweets_f, user_clean_tweets_f):

    try:
        # crawl user profile
        # sys.stdout.write('Get user profile >> ')
        # sys.stdout.flush()
        if not os.path.exists(os.path.join(user_dir, user_profile_f)):
            os.system("twarc users %s > %s" % (screen_name, os.path.join(user_dir, user_profile_f)))

        # crawl user profile image
        # sys.stdout.write('Get user profile image >> ')
        # sys.stdout.flush()

        with open(os.path.join(user_dir, user_profile_f)) as rf:
            user_profile_json = json.load(rf)
            
            if not os.path.exists(os.path.join(user_dir, user_profileimg_f)):

                # extract user profile image url
                user_profileimg_url = user_profile_json['profile_image_url']

                def image_converter(user_profileimg_url):
                    tmp_file = 'user/tmp' + user_profileimg_url[-4:]
                    urllib.urlretrieve(user_profileimg_url, tmp_file)
                    from PIL import Image
                    im = Image.open(tmp_file)
                    rgb_im = im.convert('RGB')
                    rgb_im.save(os.path.join(user_dir, user_profileimg_f))
                    os.remove(tmp_file)

                if user_profileimg_url:
                    user_profileimg_url = user_profileimg_url.replace('_normal', '_bigger')
                    # urllib.urlretrieve(user_profileimg_url, os.path.join(user_dir, user_profileimg_f))
		    
            image_converter(user_profileimg_url)

        # crawl user tweets
        # sys.stdout.write('Get user tweets >> ')
        # sys.stdout.flush()
        if not os.path.exists(os.path.join(user_dir, user_tweets_f)):
            os.system("twarc timeline %s > %s" % (screen_name, os.path.join(user_dir, user_tweets_f)))

        # clean user tweets
        # sys.stdout.write('Clean user tweets \n')
        # sys.stdout.flush()
        if not os.path.exists(os.path.join(user_dir, user_clean_tweets_f)):

            tweet_raw_lines = []
            with open(os.path.join(user_dir, user_tweets_f)) as rf:
                for line in rf:
                    tweet_raw_lines.append(json.loads(line)['full_text'])

            clearn_tweets = process_raw_tweets(tweet_raw_lines)

            with open(os.path.join(user_dir, user_clean_tweets_f), 'w') as wf:
                for tweet in clearn_tweets:
                    if len(tweet) > 0:
                        wf.write(tweet.encode('utf-8') + '\n')
            wf.close()

        return user_profile_json

    except Exception as e:
		# print e
    	print "Could not predict user's role. Check account info, few tweets, incorrect image format..."
        # sys.exit(1)


def role_classifier(screen_name):

    try:

        user_dir = 'user'

        user_profile_f = screen_name + '.json'
        user_profileimg_f = screen_name + '.jpg'
        user_tweets_f = screen_name + '_tweets.json'
        user_clean_tweets_f = screen_name + '.csv'

        user_profile_json = user_info_crawler(screen_name, user_dir, user_profile_f, user_profileimg_f, user_tweets_f, user_clean_tweets_f)

        # create a one row dataframe
        user_df = pd.DataFrame(columns=['name', 'screen_name', 'desc', 'follower', 'following'])

        user_df.loc[-1] = [user_profile_json['name'], user_profile_json['screen_name'], user_profile_json['description'], 
                       user_profile_json['followers_count'], user_profile_json['friends_count']]

        # ============================================
        # basic feature calculation and prediction
        # ============================================

        # sys.stdout.write('Classifier 1 >> ')
        # sys.stdout.flush()

        name_score = sc.name_score(user_df.name)
        screen_name_score = sc.screen_name_score(user_df.screen_name)
        desc_score, desc_words = sc.desc_score(user_df.desc)
        network_score = sc.network_score(user_df.follower, user_df.following)
        _, _, prof_img_v_score = sc.prof_img_score(user_df.screen_name, user_dir)
        first_score, inter_score, emo_score = sc.first_inter_emo_score(user_df.screen_name, user_dir, "All")

        # convert format
        TML_1_testing = pd.DataFrame()
        TML_1_testing['user'] = user_df.screen_name
        TML_1_testing['name_score'] = name_score
        TML_1_testing['screen_name_score'] = screen_name_score
        TML_1_testing['desc_score'] = desc_score
        TML_1_testing['desc_words'] = desc_words
        TML_1_testing['network_score'] = network_score
        TML_1_testing['prof_img_score'] = prof_img_v_score
        TML_1_testing['first_score'] = first_score
        TML_1_testing['inter_score'] = inter_score
        TML_1_testing['emo_score'] = emo_score

        classifier_1 = pickle.load(open('model/classifier_1.pkl', 'r'))
        classifier_1_predict = classifier_1.predict_proba(TML_1_testing[list(TML_1_testing)[1:]])

        # ============================================
        # advanced feature calculation and prediction
        # ============================================

        # sys.stdout.write('Classifier 2 >> ')
        # sys.stdout.flush()

        ktop_words_dict = pickle.load(open('conf/ktop_words.pkl', 'r'))
        ktop_words_score = sc.ktop_words_score(user_df.screen_name, ktop_words_dict, user_dir, 20)

        # convert format
        TML_2_testing = pd.DataFrame()
        TML_2_testing['user'] = user_df.screen_name
        for i in range(60):
            TML_2_testing['k_top_' + str(i)] = np.array(ktop_words_score)[:, i]

        classifier_2 = pickle.load(open('model/classifier_2.pkl', 'r'))
        classifier_2_predict = classifier_2.predict_proba(TML_2_testing[list(TML_2_testing)[1:]])

        # ============================================
        # deep learning section
        # ============================================

        # sys.stdout.write('Classifier 3 >> ')
        # sys.stdout.flush()

        net = ResNet18()
        net.load_state_dict(torch.load('model/classifier_3.pkl'))

        transform = transforms.Compose([
            transforms.Scale(224),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
        ])

        def image_loader(image_name):
            image = Image.open(image_name)
            image = transform(image).float()
            image = Variable(image)
            iamge = image.unsqueeze_(0)
            return image

        classifier_3_predict = net(image_loader(os.path.join(user_dir, user_profileimg_f))).data.cpu().numpy().tolist()

        # ============================================
        # hybrid model prediction
        # ============================================
        
        # sys.stdout.write('Hybrid Classifier \n')
        # sys.stdout.flush()

        hybrid_testing = np.concatenate((classifier_1_predict[0], classifier_2_predict[0], classifier_3_predict[0]))

        classifier_hybrid = pickle.load(open('model/classifier_hybrid.pkl', 'r'))
        output = classifier_hybrid.predict_proba([hybrid_testing]) * 100.0

        label_list = ['Brand', 'Female', 'Male']

        print '%-6s' % label_list[np.argmax(output[0])],
        print ' [Male: %.1f%%, Female: %.1f%%, Brand: %.1f%%]' % (output[0][2], output[0][1], output[0][0])

        # print '----------------------------------------------------------------'
        # print 'Predict Result:  Male: %.1f%%    Female: %.1f%%    Brand: %.1f%%' % (output[0][2], output[0][1], output[0][0])
        # print '----------------------------------------------------------------'

        return label_list[np.argmax(output[0])]

    except Exception as e:
		# print e
    	print "Could not predict user's role. Check account info, few tweets, incorrect image format..."
        # sys.exit(1)


def main(args):

    screen_name = args.user
    screen_name_file = args.file

    if screen_name is not None:

    	# start_time = time.time()

        sys.stdout.write("Task 1: %s  =>  " % screen_name)
        sys.stdout.flush()
        role_classifier(screen_name)

        # end_time = time.time()
        # print 'Time Cost: %s seconds' % (end_time - start_time)

    else:
        with open(screen_name_file, 'r') as rf:
            screen_name_list = list(csv.reader(rf))
        
        for idx, screen_name in enumerate(screen_name_list):
            sys.stdout.write("Task %4d: %-20s  =>  " % (idx + 1, screen_name[0]))
            sys.stdout.flush()
            role_classifier(screen_name[0])


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="A Hybrid Model for Role-related User Classification on Twitter")
    parser.add_argument('-u', '--user', default=None, type=str, help="take a user's screen_name as input")
    parser.add_argument('-f', '--file', default=None, type=str, help="take a list of users' screen_names as input")
    
    args = parser.parse_args()
    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        print 
        sys.exit(1)

    main(args)
